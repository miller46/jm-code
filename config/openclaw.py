from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

SUBMIT_PR_TOOL_FILE_LOCATION = str(SCRIPTS_DIR / "submit_pr.py")
SUBMIT_PR_REVIEW_TOOL_FILE_LOCATION = str(SCRIPTS_DIR / "submit_pr_review.py")
