"""
STEP 4: Information Extractor using Google Gemini AI
====================================================
This script reads transcript text and extracts structured restaurant information.

HOW IT WORKS:
- Takes the .txt transcript files from Step 3
- Sends the text to Google Gemini AI with specific instructions
- Gemini reads the transcript and identifies:
    * Restaurant name
    * Location/address
    * Type of food
    * Price range
    * Crowd level (based on reviewer's description)
    * Overall rating/sentiment
    * Best time to visit
    * Key dishes mentioned
- Saves this structured info as JSON files

WHAT IS GEMINI?
- Gemini is Google's AI model (like ChatGPT, but by Google)
- We use it via an API (Application Programming Interface)
- API = a way for your Python code to talk to Google's AI servers
- You send text → Google processes it → you get back structured data

WHAT IS JSON?
- JSON = JavaScript Object Notation
- It's a way to store structured data in a file
- Example:
  {
    "restaurant_name": "MTR",
    "location": "Lalbagh Road, Bengaluru",
    "price_for_two": "300-400 INR"
  }
- Python can easily read and write JSON files

WHAT IS AN API KEY?
- An API key is like a password that proves you're allowed to use Gemini
- Google gives you a free key from Google AI Studio
- Never share your API key with anyone!
"""

from google import genai                  # NEW official Google Gemini SDK
import json
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
# This reads your GEMINI_API_KEY from the .env file
load_dotenv()

# Define folder paths
TRANSCRIPTS_DIR = Path(__file__).parent.parent / "videos" / "transcripts"
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Path where we'll save all restaurant data
RESTAURANTS_DB_PATH = DATA_DIR / "restaurants.json"


def setup_gemini():
    """
    Sets up the connection to Google Gemini AI.
    
    This function:
    1. Reads your API key from the .env file
    2. Creates a Gemini client using the new google-genai SDK
    3. Returns a client object you can use to chat with Gemini
    """
    # os.getenv reads a variable from your .env file
    api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key or api_key == "your_gemini_api_key_here":
        raise ValueError(
            "\n[ERROR] Gemini API key not found!\n"
            "   1. Go to https://aistudio.google.com/apikey\n"
            "   2. Create a free API key\n"
            "   3. Open the .env file in your project\n"
            "   4. Replace 'your_gemini_api_key_here' with your actual key"
        )
    
    # Create a Gemini client with your API key
    # This is the new way to use Gemini (google-genai SDK)
    client = genai.Client(api_key=api_key)
    
    print("[OK] Gemini AI connected successfully!")
    return client


def extract_restaurant_info(transcript_text: str, client, video_filename: str, title: str = "", description: str = "") -> dict:
    """
    Uses Gemini AI to extract restaurant information from transcript text, video title, and description.
    
    Parameters:
        transcript_text (str): The transcript of the food review video
        client: The Gemini client object
        video_filename (str): Name of the video file (used as source reference)
        title (str): Video title if available
        description (str): Video description if available
        
    Returns:
        dict: Structured restaurant information as a Python dictionary
    """
    
    meta_context = ""
    if title or description:
        meta_context = f"""
VIDEO TITLE: {title or 'Unknown'}
VIDEO DESCRIPTION: {description or 'None provided'}

CRITICAL EXTRACTION GUIDELINES:
1. **VIDEO DESCRIPTION IS HIGHEST PRIORITY FOR ACCURACY**: Food creators regularly write the exact restaurant name, Google Maps address, landmark, price list, and operating hours in the VIDEO DESCRIPTION.
   - If audio pronunciation is unclear, trust the spelled-out name in the TITLE or DESCRIPTION.
   - Look in the description for keywords like "Location", "Address", "Opposite", "Near", "Timings", "Price".
2. **COMBINE AUDIO & DESCRIPTION**: Cross-reference the dishes spoken in the transcript with the locations listed in the description.
"""

    prompt = f"""
You are an expert at analyzing food review videos and extracting restaurant information.
{meta_context}
TRANSCRIPT:
{transcript_text}

Extract the following information and return it as a JSON object.
If any field is not mentioned in the transcript or description, use null.
Be realistic and only extract what's actually mentioned.

Return ONLY a valid JSON object with this exact structure (no other text):
{{
    "restaurant_name": "Name of the restaurant or food place",
    "city": "City where the restaurant is located",
    "area_or_locality": "Specific area, street, or landmark near the restaurant",
    "full_address": "Full address if mentioned in description/video, otherwise null",
    "cuisine_type": "Type of food (South Indian, North Indian, Chinese, etc.)",
    "meal_type": ["breakfast", "lunch", "dinner", "snacks"],
    "price_range": {{
        "description": "Budget/Mid-range/Expensive or description from video",
        "approximate_cost_for_two": "Amount in INR if mentioned, else null"
    }},
    "crowd_level": {{
        "description": "How crowded the reviewer said it was",
        "best_time_to_visit": "Time when it's less crowded, if mentioned",
        "usually_crowded_at": "Times when it's usually packed, if mentioned"
    }},
    "rating": {{
        "reviewer_sentiment": "Positive/Negative/Mixed",
        "score_if_given": "Rating out of 5 or 10 if reviewer mentioned one"
    }},
    "must_try_dishes": ["List of dishes highly recommended in the video"],
    "ambience": "Description of the place's atmosphere (family-friendly, casual, formal, etc.)",
    "special_notes": "Any other important info (timings, parking, reservations, etc.)",
    "source_video": "{video_filename}"
}}
"""

    
    print(f"[AI] Asking Gemini to analyze transcript...")
    
    # Send the prompt to Gemini with quota-resilient model fallback
    response = None
    for model_name in ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash", "gemini-3.8-flash"]:
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            if response and response.text:
                break
        except Exception:
            continue
    if not response or not response.text:
        return {}
    
    # response.text contains Gemini's reply as a string
    response_text = response.text.strip()
    
    # Sometimes Gemini wraps JSON in markdown code blocks like ```json ... ```
    # We need to clean that up before parsing
    if response_text.startswith("```"):
        # Remove the first line (```json) and last line (```)
        lines = response_text.split("\n")
        response_text = "\n".join(lines[1:-1])
    
    # json.loads() converts a JSON string into a Python dictionary
    restaurant_data = json.loads(response_text)
    
    # Ensure critical schema invariants
    if not isinstance(restaurant_data.get("meal_type"), list) or not restaurant_data.get("meal_type"):
        restaurant_data["meal_type"] = ["lunch", "dinner"]
    if not isinstance(restaurant_data.get("must_try_dishes"), list) or not restaurant_data.get("must_try_dishes"):
        restaurant_data["must_try_dishes"] = ["Special Dish"]
    
    # Clean state names returned instead of city
    STATE_NAMES_BLOCKED = {
        "telangana", "andhra pradesh", "karnataka", "tamil nadu", "kerala",
        "maharashtra", "delhi", "gujarat", "rajasthan", "uttar pradesh"
    }
    raw_city = (restaurant_data.get("city") or "").strip()
    if raw_city.lower() in STATE_NAMES_BLOCKED:
        restaurant_data["city"] = "Unknown"

    # Clean redundant city suffix
    city = restaurant_data.get("city", "")
    name = restaurant_data.get("restaurant_name", "")
    if city and name.lower().endswith(f"- {city.lower()}"):
        restaurant_data["restaurant_name"] = name[: -(len(city) + 2)].strip()

    print(f"[OK] Extracted info for: {restaurant_data.get('restaurant_name', 'Unknown')}")
    return restaurant_data


def load_existing_database() -> list:
    """
    Loads the existing restaurants database from the JSON file.
    If no database exists yet, returns an empty list.
    """
    if RESTAURANTS_DB_PATH.exists():
        with open(RESTAURANTS_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_database(restaurants: list):
    """
    Saves the restaurants list to the JSON database file.
    """
    with open(RESTAURANTS_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(restaurants, f, indent=2, ensure_ascii=False)
    print(f"[SAVE] Database saved: {len(restaurants)} restaurants in {RESTAURANTS_DB_PATH}")


def process_all_transcripts() -> list:
    """
    Processes ALL transcript files and extracts restaurant information.
    """
    transcript_files = list(TRANSCRIPTS_DIR.glob("*.txt"))
    
    if not transcript_files:
        print("[WARN]  No transcript files found!")
        print("   Run step3_transcriber.py first!")
        return []
    
    print(f"[FOLDER] Found {len(transcript_files)} transcript files to process")
    
    # Setup Gemini connection (once, then reuse for all files)
    client = setup_gemini()
    
    # Load existing database
    restaurants = load_existing_database()
    already_processed = {r.get("source_video", "") for r in restaurants}
    
    for i, transcript_file in enumerate(transcript_files, 1):
        print(f"\n{'='*50}")
        print(f"Processing {i} of {len(transcript_files)}: {transcript_file.name}")
        
        if transcript_file.name in already_processed:
            print(f"[SKIP]  Already processed, skipping.")
            continue
        
        try:
            with open(transcript_file, "r", encoding="utf-8") as f:
                transcript_text = f.read()
            
            if not transcript_text.strip():
                print("[WARN]  Empty transcript, skipping.")
                continue
            
            # Check if .meta.json exists for this transcript
            meta_file = transcript_file.with_suffix(".meta.json")
            video_title = ""
            video_desc = ""
            if meta_file.exists():
                try:
                    with open(meta_file, "r", encoding="utf-8") as mf:
                        meta_data = json.load(mf)
                        video_title = meta_data.get("title", "")
                        video_desc = meta_data.get("description", "")
                except Exception:
                    pass

            restaurant_info = extract_restaurant_info(
                transcript_text, client, transcript_file.name,
                title=video_title, description=video_desc
            )
            
            restaurants.append(restaurant_info)
            save_database(restaurants)
            
        except json.JSONDecodeError as e:
            print(f"[ERROR] Gemini returned invalid JSON for {transcript_file.name}: {e}")
        except Exception as e:
            print(f"[ERROR] Error processing {transcript_file.name}: {e}")
    
    print(f"\n[DONE] Processing complete! {len(restaurants)} restaurants in database.")
    return restaurants


if __name__ == "__main__":
    restaurants = process_all_transcripts()
    
    if restaurants:
        print("\n[STATS] Restaurant Database Summary:")
        print("-" * 40)
        for r in restaurants:
            name = r.get("restaurant_name", "Unknown")
            city = r.get("city", "Unknown city")
            cuisine = r.get("cuisine_type", "Unknown cuisine")
            print(f"  [FOOD]  {name} | {city} | {cuisine}")
