# Taken and modified from:
# https://blog.alexparunov.com/upserting-update-and-insert-with-pandas
# https://gist.github.com/alexparunov/630b61c00c50dce40bb2bc9ebb3f28a0

import sqlalchemy as db
import pandas as pd
from sqlalchemy.dialects.postgresql import insert
def create_upsert_method(meta):
    """
    Create upsert method that satisfied the pandas's to_sql API.
    """
    def method(table, conn, keys, data_iter):
        # select table that data is being inserted to (from pandas's context)
        sql_table = db.Table(table.name, meta, autoload_with=conn)
        
        # list of dictionaries {col_name: value} of data to insert
        values_to_insert = [dict(zip(keys, data)) for data in data_iter]

        # New data does not have an id and 'Null' values can't exist.
        # The database will normally auto-assign the id anyways.
        # But I was still having problems with assigned id's, and dropping them
        #   doesn't seem to affect the database. Perhaps better to drop the column ahead.
        try:
            for i in values_to_insert:
                #if pd.isna(i['id']):
                i.pop('id')
        except:
            pass

        # create insert statement using postgresql dialect.
        insert_stmt = insert(sql_table).values(values_to_insert)
        # create update statement for excluded fields on conflict
        update_stmt = {x.key: x for x in insert_stmt.excluded}
        #print(update_stmt)
        # create upsert statement. 
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=['metadata_id','start_ts'], # index elements are primary keys of a table
            #index_elements=sql_table.primary_key.columns, # index elements are primary keys of a table
            set_=update_stmt # the SET part of an INSERT statement
        )
        
        # execute upsert statement
        conn.execute(upsert_stmt)

    return method
