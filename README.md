# DIS Project - ErDerSol.dk

[erdersol-dk.onrender.com](https://erdersol-dk.onrender.com)

## Description

- Web app for finding outdoor seating places in Copenhagen.
- Helps users find places to enjoy a beer in the sun.
- Built with Flask, JavaScript, MapLibre, Supabase, and PostgreSQL.

## Database model
- The database is hosted on Supabase.

ER-diagram with crow's foot notation:

![ER diagram is found in root directory](https://github.com/magic-markk/ErDerSol.dk/blob/main/margin-ER-Diagram%202.0.png "ErDerSol ER-diagram")

The two tables have a "one and only one to zero or many" relation.


## Setup

#### Setting up repository and requirements installation:

```bash
git clone https://github.com/magic-markk/ErDerSol.dk.git
cd ErDerSol.dk
pip install -r requirements.txt
```

#### Setting up database:

Run the SQL script `supabase/create_outdoor_seating_places_table.sql` to set up DB table containing venues with outdoor seating. Afterwards, run the SQL script `supabase/create_bar_shadow_cache_table.sql` to create the cache table for storing shadow, building, and weather data for the venues.

Use the existing CSV file `outdoor_seating_places.csv` to fill the `outdoor_seating_places` table. Import the CSV into Supabase after running `supabase/create_outdoor_seating_places_table.sql`.


## Environment variables

Create a `.env` file in the project root:

```env
DATABASE_URL=[Supabase database url]
MY_EMAIL=[Specific email to use for met.no API queries]
```

Do not commit `.env`.

## Run

```bash
cd website
flask --app app run
```

If `flask --app app run` does not work, use:

```bash
cd website
python app.py
```

If `python` does not work, use:

```bash
cd website
python3 app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Usage

- View venues on the map.
- Click venues for information.
- Search by name or address.
- Use location button to center map on user location. This also sends a search query of bars and pubs within 3km of your location and ranks them based on how much sun the venue has, as well as other metrics specified in the file `sun_app/bar_scoring.py`. Be aware that this may take a while on venues that have not yet been recently cached.

## Current URL we host the web app on
[erdersol-dk.onrender.com](https://erdersol-dk.onrender.com)

This is done on Render.com's free hosting plan, so application may need 30 seconds to start.
