"""
Step 3 + 4 combined: Extract restaurant info from transcript and get suggestion.
Run this after transcription is done.
"""
import sys, os, json, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from google import genai
from dotenv import load_dotenv
load_dotenv()

# -------------------------------------------------------
# STEP 3: Extract restaurant info with Gemini
# -------------------------------------------------------
txt_files = list(Path('videos/transcripts').glob('*.txt'))
if not txt_files:
    print('[ERROR] No transcript files found! Run transcription first.')
    sys.exit(1)

transcript_file = txt_files[0]
transcript = transcript_file.read_text(encoding='utf-8')
print(f'[STEP 3] Transcript loaded: {len(transcript)} characters')
print()

# Show preview
print('TRANSCRIPT PREVIEW (first 400 chars):')
print('-'*50)
print(transcript[:400].encode('ascii', errors='replace').decode())
print('-'*50)
print()

client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

# We send only first 8000 chars to stay within limits
# (the transcript is 23k chars - future improvement: process in chunks)
transcript_chunk = transcript[:8000]

prompt = (
    "You are an expert at analyzing food review videos and extracting restaurant information.\n\n"
    "Analyze the following transcript from a Bengaluru food tour video and extract ALL restaurants mentioned.\n\n"
    "TRANSCRIPT:\n"
    + transcript_chunk +
    "\n\nExtract information for EACH restaurant mentioned and return a JSON ARRAY.\n"
    "For each restaurant, use this structure:\n"
    "[\n"
    "  {\n"
    '    "restaurant_name": "name",\n'
    '    "city": "Bengaluru",\n'
    '    "area_or_locality": "area if mentioned, else null",\n'
    '    "cuisine_type": "type of food",\n'
    '    "meal_type": ["breakfast", "lunch", "dinner", "snacks"],\n'
    '    "price_range": {"description": "budget/mid/expensive", "approximate_cost_for_two": "amount or null"},\n'
    '    "crowd_level": {"description": "crowded/quiet etc", "best_time_to_visit": "time or null", "usually_crowded_at": "time or null"},\n'
    '    "rating": {"reviewer_sentiment": "Positive/Negative/Mixed", "score_if_given": null},\n'
    '    "must_try_dishes": ["dish1", "dish2"],\n'
    '    "ambience": "casual/formal/street food etc",\n'
    '    "special_notes": "any extra info"\n'
    "  }\n"
    "]\n\n"
    "Return ONLY a valid JSON array. No explanations, no markdown, just the JSON."
)

# Try models in priority order
models_to_try = ['gemini-3.5-flash', 'gemini-3.8-flash', 'gemini-3.6-flash', 'gemini-3.7-flash']
data = None

for model_name in models_to_try:
    try:
        print(f'[STEP 3] Trying Gemini model: {model_name} ...')
        response = client.models.generate_content(model=model_name, contents=prompt)
        text = response.text.strip()
        # Clean up markdown code blocks if Gemini wraps in them
        if text.startswith('```'):
            text = '\n'.join(text.split('\n')[1:-1])
        data = json.loads(text)
        print(f'[OK] Success with {model_name}! Found {len(data)} restaurants.')
        break
    except Exception as e:
        err = str(e)[:120]
        print(f'  Failed ({err})')
        print('  Waiting 3 seconds before trying next model...')
        time.sleep(3)

if not data:
    print('[ERROR] All Gemini models failed. Please try again in a few minutes.')
    sys.exit(1)

# Save to database
Path('data').mkdir(exist_ok=True)
Path('data/restaurants.json').write_text(
    json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8'
)
print()
print('EXTRACTED RESTAURANTS:')
print('='*50)
for r in data:
    name = r.get('restaurant_name', 'Unknown')
    cuisine = r.get('cuisine_type', 'Unknown')
    dishes = ', '.join(r.get('must_try_dishes', [])[:3])
    crowd = r.get('crowd_level', {}).get('description', 'Not mentioned')
    sentiment = r.get('rating', {}).get('reviewer_sentiment', 'Unknown')
    print(f'  Restaurant : {name}')
    print(f'  Cuisine    : {cuisine}')
    print(f'  Must try   : {dishes}')
    print(f'  Crowd      : {crowd}')
    print(f'  Review     : {sentiment}')
    print()

print(f'Saved {len(data)} restaurants to data/restaurants.json')

# -------------------------------------------------------
# STEP 4: Get personalized suggestion
# -------------------------------------------------------
print()
print('='*60)
print('[STEP 4] Getting your restaurant suggestion...')
print('='*60)

# Build the suggestion prompt
restaurants_text = json.dumps(data, indent=2, ensure_ascii=False)
suggestion_prompt = (
    "You are a helpful local food guide who knows Bengaluru very well.\n\n"
    "The user is at: Bengaluru Railway Station (KSR / City Railway Station)\n"
    "Current time: 2:00 PM\n"
    "Available time: 2 hours total (must return to station within 2 hours)\n"
    "Preference: vegetarian-friendly options preferred\n\n"
    "Here is restaurant data from food review videos:\n\n"
    + restaurants_text +
    "\n\nBased on this, suggest the BEST 1-2 restaurants.\n"
    "Consider: time constraint (2hrs round trip), time of day (2pm = lunch), crowd levels, food quality.\n\n"
    "Format your response clearly with:\n"
    "- Restaurant name\n"
    "- Why you recommend it\n"
    "- What to order\n"
    "- Crowd situation at 2pm\n"
    "- Getting there (based on available info)\n"
    "- Important caveats (this data is from videos, verify before going)\n"
)

for model_name in models_to_try:
    try:
        print(f'Using model: {model_name}')
        response = client.models.generate_content(model=model_name, contents=suggestion_prompt)
        suggestion = response.text
        print()
        print('YOUR RECOMMENDATION:')
        print('='*60)
        print(suggestion)
        print('='*60)
        Path('data/last_suggestion.txt').write_text(suggestion, encoding='utf-8')
        print()
        print('Saved to data/last_suggestion.txt')
        break
    except Exception as e:
        print(f'Failed: {str(e)[:100]}')
        time.sleep(3)
