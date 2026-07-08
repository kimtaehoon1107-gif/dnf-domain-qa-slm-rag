import argparse
import json
import sys
from pathlib import Path

from io_utils import read_jsonl
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.pipeline import Pipeline


def evaluate_split(model: Pipeline, rows: list[dict], label_name: str, split_name: str) -> dict:
    x_eval = [row["question"] for row in rows]
    y_eval = [row[label_name] for row in rows]
    predictions = model.predict(x_eval)
    return {
        "split": split_name,
        "rows": len(rows),
        "accuracy": accuracy_score(y_eval, predictions),
        "classification_report": classification_report(y_eval, predictions, zero_division=0, output_dict=True),
        "examples": [
            {
                "question": row["question"],
                "expected": expected,
                "predicted": predicted,
            }
            for row, expected, predicted in zip(rows, y_eval, predictions)
        ],
    }


def train_and_eval(rows: list[dict], label_name: str) -> dict:
    train_rows = [row for row in rows if row.get("split") == "train"]
    dev_rows = [row for row in rows if row.get("split") == "dev"]
    test_rows = [row for row in rows if row.get("split") == "test"]
    eval_rows = dev_rows or test_rows
    if not train_rows or not eval_rows:
        raise ValueError("Train rows and at least one dev/test split are required.")

    model = Pipeline(
        [
            ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=1)),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]
    )
    x_train = [row["question"] for row in train_rows]
    y_train = [row[label_name] for row in train_rows]
    model.fit(x_train, y_train)

    evaluations = {}
    if dev_rows:
        evaluations["dev"] = evaluate_split(model, dev_rows, label_name, "dev")
    if test_rows:
        evaluations["test"] = evaluate_split(model, test_rows, label_name, "test")
    primary_split = "test" if test_rows else "dev"
    primary = evaluations[primary_split]

    return {
        "label": label_name,
        "train_rows": len(train_rows),
        "dev_rows": len(dev_rows),
        "test_rows": len(test_rows),
        "primary_eval_split": primary_split,
        "accuracy": primary["accuracy"],
        "classification_report": primary["classification_report"],
        "examples": primary["examples"],
        "evaluations": evaluations,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train lightweight label classifiers for intent and answerability.")
    parser.add_argument("--qa", type=Path, default=Path("data/processed/qa_dataset.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("outputs/label_classifier_report.json"))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    rows = read_jsonl(args.qa)
    report = {
        "intent": train_and_eval(rows, "intent"),
        "answerability": train_and_eval(rows, "answerability"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "output": str(args.output),
        "intent_accuracy": report["intent"]["accuracy"],
        "answerability_accuracy": report["answerability"]["accuracy"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
