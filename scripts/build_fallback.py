import csv
from pathlib import Path

# This script reads a tab-separated text file containing US city data and 
# converts it into a CSV format suitable for fallback location resolution.

def main():
    base_dir = Path(__file__).resolve().parents[1]
    input_path = base_dir / "data" / "US.txt"
    output_path = base_dir / "data" / "us_places_fallback.csv"

    with input_path.open("r", encoding="utf-8", newline="") as input_file:
        with output_path.open("w", encoding="utf-8", newline="") as output_file:
            writer = csv.writer(output_file)
            writer.writerow(["city_ascii", "state_id", "lat", "lng", "population"])
            for line in input_file:
                columns = line.rstrip("\r\n").split("\t")
                if len(columns) < 15 or columns[6] != "P":
                    continue

                writer.writerow([
                    columns[2],
                    columns[10],
                    columns[4],
                    columns[5],
                    columns[14],
                ])


if __name__ == "__main__":
    main()
