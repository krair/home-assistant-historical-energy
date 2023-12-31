# Home Assistant Energy Importer

![energy data in home assistant](screenshot-long-interval.webp "Long Term Statistics")
---
![energy data in home assistant](screenshot-short-interval.webp "Long Term Statistics")
---

### FR
J'ai commencé ce projet en pensant à Enedis, car je vis en France. Malheureusement, mon français écrit est très médiocre. Peut-être qu'un jour il s'améliorera et que je pourrai écrire ceci en français également. Je suis desolé.

### EN

**Note that this is still very much a work in progress! Please be careful with your data!**

This project was heavily inspired by others with the same requirements: Inserting energy data into Home Assistant. The one catch being that we cannot natively insert data after it has occurred. This is a huge problem for some, as my electricity provider, Enedis, does not report real-time usage. Instead, we have access only to the data from the previous day, all at once. Thus, if we'd like to track our usage, it must be imported retroactively.

Inspirations and credit:
- https://github.com/bokub/ha-linky
- https://github.com/patrickvorgers/HA-Import-Toon-Data/blob/main/Toon.sql
- https://gist.github.com/alexparunov/630b61c00c50dce40bb2bc9ebb3f28a0

## Why not use an existing project?

I really like what was done on https://github.com/bokub/ha-linky. In fact I wanted to use it in my own instance. However, there were two factors that held me back: 

1) Add-ons don't work in containerized installations of Home Assistant (and it isn't currently in HACS)
2) Costs cannot be easily attached with their method used. 

Furthermore, the above project only works for Enedis users with a Linky meter in France. I hoped to create something that the wider community could also use with more generic and boilerplate code to assist others who don't want to dive into SQL directly.

## Pre-Installation

This container is currently optimized to work with the API made available (for free) by https://conso.boris.sh/ for Enedis users in France. It *should* be easy enough to adapt this project to any other API service elsewhere, but will take some customizing as I have no access to any other API's. If you decide to use the above API, consider giving them a THANK YOU on their GitHub page or buy them a coffee (although I could not find a link for it on their site at the time of writing this!)

If you are in France (and wish to use the above service), first head to their page and follow the instructions listed. You should end up with an API token at the end. This is what will allow us to communicate with the service.

For others, give it a try, create an issue or PR, and we will see if we can get other services working.

### Energy sensor in HA

I didn't have an energy sensor created already, so created mine with the following in my Home Assistant's `configuration.yaml` file:

```{yaml}
template:
  - sensor:
      - name: Enedis Consumption Total
        state: "{{ states('sensor.enedis_consumption_total') }}"
        availability: "{{ states('sensor.enedis_consumption_total') > 0 }}"
        unit_of_measurement: kWh
        device_class: energy
        state_class: total_increasing
```

Note: The `state` and `availability` statements are there to insure we don't get erroneous "0" readings thrown into the current statistics - Home Assistant assumes we can read the data real-time. 

Restart Home Assistant. This will create the sensor in Home Assistant. Then by going to the "Energy" dashboard, add this sensor to the "Energy Grid" card under the "Grid Consumption" section. After adding the sensor, you should be able to select a cost for the energy. For me, this didn't actually start tracking the cost, but it did create a sensor called `sensor.enedis_consumption_total_cost`. This is what I use to import costs into using this app.

### MAKE A BACKUP

In all cases, you should **start by making a good backup** of your Home Assistant database in case something goes wrong!

### Non-API file imports

Currently, I haven't written in a way to import directly from a file like a CSV or JSON. Although I did use this method extensively while developing this app. Thus it is a relatively trivial addition I can make if there is a request for it.

## Installation

Installation is as easy as cloning this repository, building the container with the `Containerfile`, modifying the `config.yaml.example` file with your parameters, and running the container. It is currently setup to run as a one-shot service. Thus, if you want it to grab data from your energy provider daily, I recommend running it using a `cron` job.

### Config File

Most of the information needed is in the comments within the config file itself. I might add more here later if needed.

Once you've put your values into the config file, I recommend mounting it into your container like such:

**Docker/Podman run:**
```
... run ... -v ./config/config.yaml:/app/config/config.yaml ...
```

**Docker/Podman compose:**

```
services:
  home-assistant-historical-energy:
    ...
    volumes:
      - ./config/config.yaml:/app/config/config.yaml
    ...
```

## Limitations

### PostgreSQL only (for now)

Currently, I've only developed it to work with PostgreSQL databases. This *should* also work with the default SQLite databases, though I didn't test it directly yet. The functionality exists in the code, but should be considered **EXPERIMENTAL** at best. Should be a relatively easy addition if there's interest in it.

### Enedis via conso.boris.sh

Since this is highly specialized for now, there may be some things that could go wrong if using a different service. Since there is currently no native Enedis integration into Home Assistant, I had to create a custom sensor for tracking, and have done the best I can to get this into my own Home Assistant.

### Production not considered

I don't (yet) produce any electricity, thus I haven't tested this with production data. It should theoretically work and not be much different, but I have no frame of reference to ensure it acts as it should!

### Standard Tariff

I am on the standard single price model, thus the app is written with such in mind. It should be relatively easy to modify this if you are on a High Tariff/Low Tariff plan (HPHC in France). I just haven't looked into this yet.

## Troubleshooting

### sqlalchemy.exc.IntegrityError: (psycopg2.errors.UniqueViolation) duplicate key value violates unique constraint

This error plagued me after migrating my default SQLite database to PostgreSQL. The problem is that during the migration, the constraints weren't copied correctly, and the main sequence column is out of sync - the database doesn't know where it should insert the "next" value, and when trying to insert (at the beginning), throws an error so not to overwrite an old value.

Thank you to [some smart people](https://sigfried.be/blog/migrating-home-assistant-sqlite-to-postgresql/#commento-846f6ff20215cca22f98543048b0dce33998cd0f75c064186c1eaf74d66c4346), I found the issue was fixable by simply resetting the database's sequence value to the highest one unused. 

You'll need to run this set of SQL statements on your database:

```sql
SELECT setval(pg_get_serial_sequence('statistics_runs', 'run_id'), coalesce(MAX(run_id), 1)) from statistics_runs;
SELECT setval(pg_get_serial_sequence('statistics_meta', 'id'), coalesce(MAX(id), 1)) from statistics_meta;
SELECT setval(pg_get_serial_sequence('statistics', 'id'), coalesce(MAX(id), 1)) from statistics;
SELECT setval(pg_get_serial_sequence('statistics_short_term', 'id'), coalesce(MAX(id), 1)) from statistics_short_term;
SELECT setval(pg_get_serial_sequence('states', 'state_id'), coalesce(MAX(state_id), 1)) from states;
SELECT setval(pg_get_serial_sequence('state_attributes', 'attributes_id'), coalesce(MAX(attributes_id), 1)) from state_attributes;
SELECT setval(pg_get_serial_sequence('events', 'event_id'), coalesce(MAX(event_id), 1)) from events;
SELECT setval(pg_get_serial_sequence('event_data', 'data_id'), coalesce(MAX(data_id), 1)) from event_data;
SELECT setval(pg_get_serial_sequence('recorder_runs', 'run_id'), coalesce(MAX(run_id), 1)) from recorder_runs;
SELECT setval(pg_get_serial_sequence('schema_changes', 'change_id'), coalesce(MAX(change_id), 1)) from schema_changes;
```

Afterwards, you shouldn't run into this error any longer.