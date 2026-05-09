import argparse
import random
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLASSES = ["enemy", "teammate", "player"]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def find_images(source: Path):
    return sorted(
        path for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def unique_name(path: Path, used: set[str]) -> str:
    stem = "_".join(path.relative_to(path.parents[1]).with_suffix("").parts)
    name = f"{stem}{path.suffix.lower()}"
    counter = 1
    while name in used:
        name = f"{stem}_{counter}{path.suffix.lower()}"
        counter += 1
    used.add(name)
    return name


def write_data_yaml(output: Path):
    lines = [
        f"path: {output.as_posix()}",
        "train: images/train",
        "val: images/val",
        "names:",
    ]
    for index, class_name in enumerate(CLASSES):
        lines.append(f"  {index}: {class_name}")
    (output / "data.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Build a YOLO dataset skeleton from captured bad vision frames."
    )
    parser.add_argument("--source", default="debug_frames/vision", help="Captured frame folder.")
    parser.add_argument("--output", default="datasets/vision_model", help="YOLO dataset output folder.")
    parser.add_argument("--val-split", type=float, default=0.2, help="Validation fraction.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--include-empty-labels",
        action="store_true",
        help="Create empty YOLO label files. Use only for unlabeled review/export, not final training.",
    )
    args = parser.parse_args()

    source = (ROOT / args.source).resolve()
    output = (ROOT / args.output).resolve()
    if not source.exists():
        raise SystemExit(f"Source folder does not exist: {source}")

    images = find_images(source)
    if not images:
        raise SystemExit(f"No captured images found in {source}")

    random.seed(args.seed)
    random.shuffle(images)
    val_count = max(1, int(len(images) * args.val_split)) if len(images) > 1 else 0
    val_images = set(images[:val_count])

    for split in ("train", "val"):
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)

    used_names = set()
    copied = {"train": 0, "val": 0}
    for image in images:
        split = "val" if image in val_images else "train"
        name = unique_name(image, used_names)
        target_image = output / "images" / split / name
        shutil.copy2(image, target_image)

        source_label = image.with_suffix(".txt")
        target_label = output / "labels" / split / f"{Path(name).stem}.txt"
        if source_label.exists():
            shutil.copy2(source_label, target_label)
        elif args.include_empty_labels:
            target_label.write_text("", encoding="utf-8")

        copied[split] += 1

    write_data_yaml(output)

    print(f"Dataset created: {output}")
    print(f"Images: {copied['train']} train, {copied['val']} val")
    print("Classes: 0 enemy, 1 teammate, 2 player")
    if not args.include_empty_labels:
        print("Next: label the images in YOLO format before training.")


if __name__ == "__main__":
    main()
