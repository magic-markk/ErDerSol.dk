# DIS Project - ErDerSol.dk

## Description

- Web app for finding outdoor seating places in Copenhagen.
- Helps users find places to enjoy a beer in the sun.
- Built with Flask, JavaScript, MapLibre, Supabase, and PostgreSQL.

## Database model

- E/R diagram: To be added.
- The database is hosted on Supabase.

## Setup

```bash
git clone https://github.com/magic-markk/ErDerSol.dk.git
cd ErDerSol.dk
pip install -r requirements.txt
```

## Environment variables

Create a `.env` file in the project root:

```env
SUPABASE_URL=[Supabase project url]
SUPABASE_SERVICE_KEY=[Supabase service role key]
```

Do not commit `.env`.

## Run

```bash
cd website
python app.py
```

If `python` does not work, use:

```bash
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
- Use location button to center map on user location.
