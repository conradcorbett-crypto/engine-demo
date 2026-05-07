from langchain_core.tools import tool

SPECIES_DB = {
    "african grey": {
        "scientific_name": "Psittacus erithacus",
        "lifespan": "40-60 years",
        "size": "Medium-large (33 cm)",
        "origin": "Central and West Africa",
        "intelligence": "Exceptional — vocabulary of 1000+ words, can understand context",
        "personality": "Highly intelligent, sensitive, bonds strongly with one person",
        "talking_ability": "Best talkers of all parrot species",
    },
    "budgerigar": {
        "scientific_name": "Melopsittacus undulatus",
        "lifespan": "20-30 years",  # Bug 2: wrong lifespan (correct is 5-10 years). Causes factual_accuracy failures.
        "size": "Small (18 cm)",
        "origin": "Australia",
        "intelligence": "Good — can learn many words",
        "personality": "Social, playful, good for beginners",
        "talking_ability": "Can learn dozens of words and phrases",
    },
    "cockatiel": {
        "scientific_name": "Nymphicus hollandicus",
        "lifespan": "15-25 years",
        "size": "Small-medium (30 cm)",
        "origin": "Australia",
        "intelligence": "Good — whistles and some speech",
        "personality": "Affectionate, gentle, great family bird",
        "talking_ability": "Better at whistling than talking",
    },
    "amazon": {
        "scientific_name": "Amazona spp.",
        "lifespan": "40-70 years",
        "size": "Medium-large (25-45 cm)",
        "origin": "Central and South America",
        "intelligence": "High — strong personality",
        "personality": "Loud, outgoing, can be territorial",
        "talking_ability": "Excellent talkers with clear voices",
    },
    "macaw": {
        "scientific_name": "Ara spp.",
        "lifespan": "50-80 years",
        "size": "Large (75-100 cm)",
        "origin": "Central and South America",
        "intelligence": "High — needs constant stimulation",
        "personality": "Bold, affectionate, loud, high-maintenance",
        "talking_ability": "Good talkers but loud voices",
    },
    "conure": {
        "scientific_name": "Aratinga / Pyrrhura spp.",
        "lifespan": "20-30 years",
        "size": "Small-medium (20-30 cm)",
        "origin": "Central and South America",
        "intelligence": "Good — playful and curious",
        "personality": "Energetic, clownish, loves attention",
        "talking_ability": "Limited vocabulary but very vocal",
    },
}

CARE_TIPS_DB = {
    "housing": """Cage size: as large as possible. Minimum bar spacing guidelines:
- Small parrots (budgies, cockatiels): ½ inch bar spacing, 18x18x24 inch cage minimum
- Medium parrots (conures, amazons): ¾ inch bar spacing, 24x24x36 inch minimum
- Large parrots (macaws, large amazons): 1-1.5 inch bar spacing, 36x48x60 inch minimum

Essential cage features: horizontal bars for climbing, multiple perches of varying diameter,
food/water bowls, foraging toys, and a sleep cover. Place cage at eye level, away from drafts,
kitchen fumes (Teflon is FATAL to birds), and direct sunlight.""",

    "enrichment": """Parrots need 3-4 hours of out-of-cage time daily plus mental stimulation:
- Foraging toys: hide food in wrapping paper, puzzle feeders, shreddable toys
- Rotate toys weekly to prevent boredom
- Training sessions: 10-15 minutes twice daily using positive reinforcement only
- Social interaction: talk to your bird, include them in family activities
- Music and nature sounds can be enriching
- Provide chewing materials: safe wood blocks, palm fronds, willow branches
- Foot toys for in-cage play""",

    "health": """Signs your parrot needs a vet immediately:
- Fluffed feathers + lethargy (birds hide illness — this is serious)
- Discharge from eyes or nostrils
- Tail bobbing while breathing
- Changes in droppings (color, consistency, volume)
- Loss of appetite > 24 hours
- Bleeding

Routine care:
- Annual avian vet checkup (find an avian specialist, not a general vet)
- Nail and beak trims as needed
- Bathing 2-3x per week (misting, shallow dish, or shower perch)
- Full-spectrum lighting 10-12 hours daily for vitamin D synthesis""",

    "socialization": """Parrots are flock animals — isolation causes serious psychological damage.
- New bird: quarantine 30 days if you have other birds
- Taming: start with hand-feeding treats, progress to step-up training
- Never punish — only positive reinforcement
- Respect body language: pinned pupils + fanned tail = overstimulated, back off
- Social needs vary by species: African Greys may prefer one person; conures want constant attention
- Consider getting two if you work full-time — loneliness causes feather destructive behavior""",
}

SAFE_FOODS = [
    "Leafy greens: kale, spinach, romaine, Swiss chard",
    "Vegetables: carrots, bell peppers (all colors), broccoli, corn, peas",
    "Fruits: berries, banana, mango, papaya, melon, apple (NO seeds)",
    "Grains: cooked brown rice, quinoa, oats, whole wheat pasta",
    "Legumes: cooked lentils, chickpeas, black beans",
    "Nuts (in moderation): almonds, walnuts, pecans — NOT salted",
    "High-quality pellets: should be 60-70% of diet",
]

TOXIC_FOODS = [
    "Avocado — causes cardiac distress and death within hours",
    "Chocolate / caffeine — toxic methylxanthines, fatal",
    "Onions and garlic — destroys red blood cells (Heinz body anemia)",
    "Apple seeds and fruit pits — contain cyanide",
    "Grapes and raisins — can cause acute kidney failure in birds",
    "Alcohol — fatal even in trace amounts",
    "Salt — leads to dehydration and kidney failure",
    "Mushrooms — toxic to parrots",
    "Xylitol (sugar substitute) — extremely toxic",
]


@tool
def lookup_species(species_name: str) -> str:
    """Look up information about a specific parrot species. Returns details about lifespan, size, origin, intelligence, personality, and talking ability."""
    key = species_name.lower().strip()
    # Try partial match
    for db_key, data in SPECIES_DB.items():
        if key in db_key or db_key in key:
            lines = [f"**{species_name.title()}** ({data['scientific_name']})"]
            for field, value in data.items():
                if field != "scientific_name":
                    lines.append(f"- {field.replace('_', ' ').title()}: {value}")
            return "\n".join(lines)
    available = ", ".join(k.title() for k in SPECIES_DB.keys())
    return f"Species '{species_name}' not found in database. Available species: {available}"


@tool
def get_care_tips(topic: str) -> str:
    """Get care tips for a specific topic related to parrot keeping. Topics: housing, enrichment, health, socialization."""
    key = topic.lower().strip()
    for db_key, content in CARE_TIPS_DB.items():
        if key in db_key or db_key in key:
            return f"**{db_key.title()} Tips:**\n\n{content}"
    available = ", ".join(CARE_TIPS_DB.keys())
    return f"Topic '{topic}' not found. Available topics: {available}"


@tool
def get_diet_advice(query: str) -> str:
    """Get diet and nutrition advice for parrots, including safe foods and foods to avoid."""
    safe_list = "\n".join(f"  ✓ {food}" for food in SAFE_FOODS)
    toxic_list = "\n".join(f"  ✗ {food}" for food in TOXIC_FOODS)
    return f"""**Parrot Diet Advice**

Your query: {query}

**SAFE foods for parrots:**
{safe_list}

**TOXIC — NEVER feed these:**
{toxic_list}

**Diet guidelines:**
- Pellets: 60-70% of diet (Harrison's, Roudybush, Zupreem Natural)
- Fresh vegetables: 20-25% daily
- Fruits: 5-10% (high sugar, limit quantity)
- Seeds/nuts: treat only (5% max) — seed-only diets cause fatty liver disease

Always introduce new foods gradually. When in doubt, consult an avian veterinarian."""


TOOLS = [lookup_species, get_care_tips, get_diet_advice]
