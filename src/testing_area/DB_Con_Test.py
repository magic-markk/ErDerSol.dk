import os

from dotenv import load_dotenv
from supabase import create_client


load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

response = (
    supabase
    .table("outdoor_seating_places")
    .select("id,name,address,lat,lon,category,google_rating")
    .limit(10)
    .execute()
)

print(response.data)
