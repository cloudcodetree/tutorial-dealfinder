# Part 1: title_brand() against the hero cast.
from dealfinder.features import title_brand

cases = [
    ("Sony WH-1000XM5 Wireless Headphones", "Sony"),
    ("COWIN E7 Active Noise Cancelling Headphones", "Cowin"),
    ("Bose QuietComfort 45 Bluetooth Wireless Over Ear Headphones", "Bose"),
    # Longest match first: Soundcore, Anker's audio line, wins over Anker.
    ("Anker Soundcore Q20i Active Noise Cancelling Headphones", "Soundcore"),
]
for title, expected in cases:
    result = title_brand(title)
    status = "✓" if result == expected else "✗"
    print(f"{status} '{result}' from: {title[:55]}")
