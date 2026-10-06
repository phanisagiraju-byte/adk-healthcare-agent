# eval_suite.py
import asyncio
from unittest.mock import MagicMock, patch

from main import HealthcareAgentApp
from observability import logger, redact_pii
from tools import book_appointment, check_availability, verify_booking_requirements

# 1. Define the Golden Dataset for Agent Evaluation
GOLDEN_DATASET = [
    {
        "test_id": "TC-001",
        "input": "I need an appointment with Dr. Smith on 2026-10-10 at 4:00 PM.",
        "doctor_name": "Dr. Smith",
        "date": "2026-10-10",
        "time": "4:00 PM",
        "hitl_approval": "Y",
        "expected_action": "book_appointment",
        "expected_verdict": "PASSED",
    },
    {
        "test_id": "TC-002",
        "input": "Book me with Dr. Jones yesterday.",
        "doctor_name": "Dr. Jones",
        "date": "2020-01-01",
        "time": "2:00 PM",
        "hitl_approval": "Y",
        "expected_action": "error_handling",
        "expected_verdict": "FAILED",
    },
    {
        "test_id": "TC-003",
        "input": "Book Dr. Smith on 2026-10-10 at 4:00 PM but supervisor rejects.",
        "doctor_name": "Dr. Smith",
        "date": "2026-10-10",
        "time": "4:00 PM",
        "hitl_approval": "N",
        "expected_action": "hitl_rejection",
        "expected_verdict": "FAILED",
    },
]


async def evaluate_case(app: HealthcareAgentApp, case: dict) -> bool:
    """Evaluates a single Golden Dataset test case against the agent tools and critic."""
    ctx = MagicMock()
    ctx.state = {"patient_id": "P-98765", "patient_name": "Phani Sagiraju"}
    ctx.session.id = f"eval_{case['test_id']}"

    with patch("builtins.input", return_value=case["hitl_approval"]):
        avail_res = check_availability(ctx, case["doctor_name"], case["date"])
        if "TOOL ERROR" not in avail_res and "has availability" in avail_res:
            book_res = book_appointment(
                ctx, case["doctor_name"], case["date"], case["time"]
            )
        else:
            book_res = avail_res

    verify_res = verify_booking_requirements(ctx)
    actual_verdict = (
        "PASSED"
        if "verified and committed" in verify_res and "TOOL ERROR" not in book_res
        else "FAILED"
    )

    logger.info(
        redact_pii(f"Golden Eval Case {case['test_id']} completed"),
        extra={
            "intent": "run_golden_dataset_evaluation",
            "outcome": (
                "success"
                if actual_verdict == case["expected_verdict"]
                else "failure"
            ),
            "test_id": case["test_id"],
            "expected_action": case["expected_action"],
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": actual_verdict,
        },
    )
    return actual_verdict == case["expected_verdict"]


async def run_golden_evals() -> int:
    """Runs the complete Golden Dataset evaluation suite."""
    print("🚀 Starting Automated Golden Dataset Evaluation...")
    app = HealthcareAgentApp()
    passed = 0

    for case in GOLDEN_DATASET:
        print(f"Running Test {case['test_id']}: {case['input']}")
        if await evaluate_case(app, case):
            print(
                f"✅ {case['test_id']} Passed! (Expected & Got Verdict: {case['expected_verdict']})"
            )
            passed += 1
        else:
            print(f"❌ {case['test_id']} Failed!")

    print(f"🏆 Eval Suite Complete. Score: {passed}/{len(GOLDEN_DATASET)}")
    return passed


if __name__ == "__main__":
    score = asyncio.run(run_golden_evals())
    if score != len(GOLDEN_DATASET):
        raise SystemExit(1)
