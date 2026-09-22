import os
import json

def extract_long_paragraphs(origin_dir="origin", output_dir="output", threshold=300):
    """
    Extracts paragraphs from text files in `origin_dir` that are strictly
    greater than `threshold` characters in length, and writes the output
    to `output_dir` as `x.long.json` where `x` is the base file name.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for filename in os.listdir(origin_dir):
        if not filename.endswith(".txt"):
            continue

        filepath = os.path.join(origin_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading file {filepath}: {e}")
            continue

        # Split content by newline to get paragraphs.
        # We strip surrounding whitespace when checking the length
        # but preserve the original paragraph string in 'origin'.
        paragraphs = content.split("\n")
        long_paragraphs_data = []

        for p in paragraphs:
            p_stripped = p.strip()
            # "大于300字的段落" -> strictly greater than 300 characters
            if len(p_stripped) > threshold:
                long_paragraphs_data.append({
                    "origin": p,
                    "split": []
                })

        # Save to output/x.long.json
        base_name = os.path.splitext(filename)[0]
        output_filename = f"{base_name}.long.json"
        output_filepath = os.path.join(output_dir, output_filename)

        try:
            with open(output_filepath, "w", encoding="utf-8") as f:
                json.dump(long_paragraphs_data, f, ensure_ascii=False, indent=2)
            print(f"Successfully processed {filename} -> {output_filename} (Found {len(long_paragraphs_data)} long paragraphs)")
        except Exception as e:
            print(f"Error writing to file {output_filepath}: {e}")

if __name__ == "__main__":
    extract_long_paragraphs()
