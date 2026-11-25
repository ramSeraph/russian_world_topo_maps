"""Prepare a Baltic warp job from verified originals and fitted frames."""

import argparse
import csv
import json
from pathlib import Path


def stage(work):
    with (work / "25k-selected-originals.csv").open() as stream:
        entries = list(csv.DictReader(stream))
    rows = []
    for entry in entries:
        sheet = Path(entry["name"]).stem
        fit = json.loads((work / "fitted" / (sheet + ".json")).read_text())
        row = fit["control"]
        if (row["scan_id"], row["original"], row["sha256"]) != (
            sheet,
            entry["name"],
            entry["sha256"],
        ):
            raise ValueError(
                f"Fitted control does not match the source manifest for {sheet}"
            )
        rows.append(row)
    if len({row["scan_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate physical sheet in source manifest")
    review = work / "georef/review"
    review.mkdir(exist_ok=True, parents=True)
    originals = review.parent / "originals"
    if not originals.exists():
        originals.symlink_to("../selected-originals", target_is_directory=True)
    elif originals.resolve() != (work / "selected-originals").resolve():
        raise ValueError(f"Unexpected original directory in {review.parent}")
    tmp = review / "controls.tmp"
    tmp.write_text(json.dumps(rows, separators=(",", ":")) + "\n")
    tmp.replace(review / "controls.json")
    print(f"Staged {len(rows)} fitted sheets")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    stage(parser.parse_args().work.resolve())
