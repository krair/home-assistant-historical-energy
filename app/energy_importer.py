'''
Script for adding historic energy data into HomeAssistant.
written by Kit Rairigh - https://github.com/krair and https://rair.dev
'''

import os
import time
import sqlalchemy as db
import json
import pandas as pd
import numpy as np
import upsert
from requests import post, get
from pytz import utc
from datetime import datetime, timedelta
import yaml

def load_config():
    with open(f'./config/config.yaml', 'r') as f:
        return yaml.safe_load(f)

def set_timezone(tz):
    '''
    Set timezone to ensure our data is pulled into HomeAssistant correctly.
    Without this, your data could be skewed by UTC +/- your timezone!
    '''
    os.environ['TZ'] = tz
    time.tzset()

def create_engine(config):
    match config.get('type'):
        case 'sqlite':
            engine = db.create_engine(f"sqlite:///{config.get('path')}")
        case 'postgresql':
            engine = db.create_engine(f"postgresql+psycopg2://{config.get('user')}:{config.get('password')}@{config.get('host')}:{config.get('port', 5432)}/{config.get('db_name')}")
        case _:
            raise Exception('DB type not "sqlite" or "postgresql"!')

    return engine.connect()

def ha_recorder_switch(config, command):
    '''Pause/resume the recorder (writing to the db's statistics) so no new 
    entries are added while we are changing the DB's statistics tables.
    '''
    url = f"{config.get('url')}/api/services/recorder/{command}"
    headers = {"Authorization": f"Bearer {config.get('api_token')}"}
    response = post(url, headers=headers)
    if response.ok:
        # log that the recorder has successfully been paused
        return True
    else:
        #raise error, exit? Retry?
        return False

def check_db_connection(conn):
    '''
    Before doing anything else, make sure the database is reachable.
    '''
    try:
        result = conn.execute(db.text("select 'ping'"))
        if result.all()[0][0] == 'ping':
            return True
        else:
            raise Exception('DB connection returned bad response.')
    except:
        raise Exception('Cannot connect to db!')

def pull_db_metadata(conn):
    '''
    Get the metadata about the existing tables.
    This facilitates writing the new data back to the database with correct parameters.
    '''
    metadata = db.MetaData()
    metadata.reflect(bind=conn)
    return metadata

def get_metadata_ids(sensor_name):
    '''
    Get the metadata id of the energy sensor where want to add the new data.
    We grab both the sensor id, as well as the sensor's cost id, if you are tracking it.
    If you aren't tracking cost, it will return None and not affect the rest.
    '''
    metadata_id_search = conn.execute(db.text(f"select id, statistic_id \
        from statistics_meta where statistics_meta.statistic_id = '{sensor_name}' \
        or statistics_meta.statistic_id = '{sensor_name}_cost'")).all()
    # Base ID is the first value, cost ID is the second value
    metadata_id = *[x for x,y in metadata_id_search if 'cost' not in y],\
    *[x for x,y in metadata_id_search if 'cost' in y]
    return metadata_id

def build_request(request_config):
    '''
    Use the config options to create the API request parameters.
    This is currently quite specific to the Enedis API.
    This function could be reworked to be more generic, but need input from others using it. 
    '''
    request_dict = {'headers': request_config.get('headers'),
            'url_req': request_config.get('url'),
            'parameters': request_config.get('parameters')}
    if request_dict['parameters']['start'] == 'yesterday':
        request_dict['parameters']['start'] = str((datetime.today() - timedelta(days=1)).date())
    else:
        try:
            request_dict['parameters']['start'] = str(request_dict['parameters']['start'])
        except:
            raise Exception('String for "start" does not follow the correct YYYY-MM-DD pattern!')
    if request_dict['parameters']['end'] == 'today':
        request_dict['parameters']['end'] = str(datetime.today().date())
    else:
        try:
            request_dict['parameters']['end'] = str(request_dict['parameters']['end'])
        except:
            raise Exception('String for "end" does not follow the correct YYYY-MM-DD pattern!')
    return request_dict

def api_request(params):
    '''
    Relatively generic API request, given the parameters. No retries built in.
    '''
    try:
        request = get(params.get("url_req"), \
            headers=params.get("headers"), \
            params=params.get("parameters"))
    except:
        raise Exception("Problem retrieving data!")
    if request.ok:
        data = request.json()
        return data
    else:
        raise Exception(f"Request not OK: Status Code {request.status_code}")

def clean_data(data, config):
    '''
    Parsing function to take the raw data and normalize it.
    Currently written in the frame of the Enedis data returned
        from https://consi.boris.sh.
    Perhaps this could be made more generic to fit other energy providers.
    '''
    # Only pull necessary data across to dataframe
    data_location = config.get("location")
    state_name = config.get("state")
    date_name = config.get("date")
    # Create list of dictionary items (to be pulled into a pandas DataFrame)
    filter_data = [{'state': j.get(state_name), 'start_ts': j.get(date_name)} for j in data.get(data_location)]
    
    # Normalize data
    df = pd.DataFrame.from_dict(filter_data, orient='columns')
    
    # Convert date to Unix timestamps as floats (if necessary)
    match df['start_ts'].dtype:
        case np.int64 | np.float64:
            pass
        case _:
            try:
                # Convert from ISO to UNIX (UTC)
                df['start_ts'] = df['start_ts'].apply(lambda x: datetime.timestamp(datetime.fromisoformat(x).astimezone(utc)))
            except:
                raise Exception('Date column is not in a familiar format (Unix or ISO)')

    
    # If needed, move data by a given amount to move the edge data points (ex: from 00:00:00 to the night
    #    before) to fix HA graph for intervals shorter than 1 day
    time_offset = config.get('time_offset')
    if time_offset:
        df['start_ts'] = df['start_ts'].apply(lambda x: x + int(time_offset))

    # Deal with DST crossover in fall (duplicate timestamps on short-term data)
    dup_idx = df[df.duplicated('start_ts')].index
    if any(dup_idx):
        # if we find any, move the duplicated entries back 1 second to avoid overlap
        df.loc[dup_idx, ['start_ts']] = [df.loc[dup_idx, ['start_ts']].apply(lambda x: x - 1)]
            
    # Rename columns to HomeAssistant's names
    #df.rename(columns={'value':'state','date':'start_ts'}, inplace=True)
    
    # Duplicate start_ts column - perhaps unnecessary
    df['created_ts'] = df['start_ts']
    
    # Conversion of given units to kWh (what HomeAssistant uses)
    cf = calculate_conversion_factor(config)
    
    match config.get('type'):
        case 'measurement':
            # Convert state values into kWh
            df['state'] = df['state'].astype(float).apply(lambda x: x * cf)
        case 'total_increasing':
            # Change state column to measurements over the given period (sum calculated later)
            df['new_state'] = df['state'].diff().fillna(df['state']).astype(float)
            df['state'] = df['new_state']
            del df_old['new_state']
        case _:
            raise Exception("Data type should be either 'measurement' or 'total_increasing'!")
    return df

def calculate_conversion_factor(config):
    '''
    If the data is not in kWh, we need to convert it. This is how we can help normalize it.
    This could be reworked to be more generic, and possibly infer the units from the data.
    For now this works for the Enedis data (given in W or Wh).
    '''
    match config.get('unit_of_measurement').lower():
        case 'kwh' | 'kw':
            unit_cf = 1
        case 'wh' | 'w':
            unit_cf = 1/1000
        case _:
            raise Exception('Unit of measurement should be in "W" or "kW"!')
    
    cf_config = float(config.get('conversion_factor', 1))
    return float(unit_cf * cf_config)
    
def generate_merged_df(conn, tables, metadata_id, df):
    '''
    Grabs all existing data for the sensor from HomeAssistant. We then join the data.
    The join is a "left-join" on the old data - this means that data already in the 
        database will take precedence, and only new timestamps will be added to the dataframe
        (our temporary holding area where we can manipulate the data using the pandas library).
    '''
    for table in tables:
        query = f"SELECT * FROM {table} WHERE metadata_id = {metadata_id}"
        
        df_old = pd.read_sql_query(query, conn)
        
        # Merge new data to be added with the old data
        df_merged = df_old.set_index(['start_ts'])\
        .combine_first(df.set_index(['start_ts'])).reset_index()
        
        # Recalculate the new sum with the added values
        df_merged['sum'] = df_merged['state'].cumsum()
        
        # Correct missing 'metadata_id' columns
        df_merged['metadata_id'].fillna(metadata_id,inplace=True)

        # Drop 'id' column as it isn't required. DB will auto-assign new rows
        #   Old id's will be found anyways with the (metadata_id, start_ts) unique constraint
        del df_merged['id']
    
        write_data_db(df_merged, table, conn)

def write_data_db(df, table, conn):
    '''
    Write the pandas dataframe into the database using a customized method to imitate the
    "upsert" (insert and on conflict update)which isn't natively available in SQLAlchemy.
    '''
    df.to_sql(table, conn, index=False, chunksize=200, if_exists="append",method=upsert_method)

# Read local config
config = load_config()

# Set timezone (default in containers is UTC)
if config.get('timezone'):
    set_timezone(config.get('timezone'))

# Create connection to the database
conn = create_engine(config['database'])
# Check the connection is available
check_db_connection(conn)
# Pull the metadata about the db's tables from the db
metadata = pull_db_metadata(conn)

# Create 'upsert' method using existing metadata
upsert_method = upsert.create_upsert_method(metadata)

# Each "sensor" gets it's own config section to ensure correct parsing and inserting
for sensor in config.get('sensors'):
    # The name of the energy sensor in HomeAssistant
    sensor_name = sensor.get('sensor_name')

    # Get the metadata_id to use in the db tables
    metadata_id = get_metadata_ids(sensor_name)
    
    # Configure the API request and run it
    request_config = build_request(sensor)
    data = api_request(request_config)
    df = clean_data(data, sensor.get('data'))
    # Temporarily disable ha's recorder from recording new statistics
    ha_recorder_switch(config.get('homeassistant'),'disable')

    # Which tables should we enter the data into (long for one measurement per day, or short for more frequent)
    match sensor.get('type'):
        case 'long':
            tables = ['statistics']
        case 'short':
            tables = ['statistics_short_term', 'statistics']

    generate_merged_df(conn, tables, metadata_id[0], df)

    # Cost per kWh
    cost = sensor.get('cost', None)

    if cost:
        # Convert measurement to monetary cost
        df['state'] = df['state'].apply(lambda x: x * cost)
        generate_merged_df(conn, tables, metadata_id[1], df)
    
    # Commit our changes and close the connection
    conn.commit()
    conn.close()
    # Re-enable ha's recorder for recording new statistics
    ha_recorder_switch(config.get('homeassistant'),'enable')
