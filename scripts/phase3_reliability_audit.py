"""Read actual ingress, runtime and delivery evidence, grouped by build and configuration."""
import argparse
import ast
from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from math import ceil
from pathlib import Path
import re
from zoneinfo import ZoneInfo


def audit(paths, build_id=None, *, now=None):
    now = now or datetime.now(UTC)
    requests, delivered, eligible, accepted, repairs = {}, set(), {}, {}, set()
    parse_errors = 0
    for path in paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not any(marker in line for marker in (
                    "event=request_started", "event=eligible_direct_reply", "event=runtime_metrics_finalized",
                    "event=reply_render_confirmed", "event=external_reply_confirmed", "event=reply_recovery_requested")):
                continue
            identity_match = re.findall(r"\brequest=([^ ]+)", line)
            if not identity_match or identity_match[-1] == "-":
                continue
            identity = identity_match[-1]
            metadata = {}
            if "metadata=" in line:
                try:
                    metadata = ast.literal_eval(line.split("metadata=", 1)[1])
                except (ValueError, SyntaxError, TypeError):
                    parse_errors += 1
                    continue
            if "event=request_started" in line:
                stamp = datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                accepted[identity] = {"request_id": identity, "started_at": stamp.isoformat(), **metadata}
            elif "event=reply_recovery_requested" in line:
                repairs.add(identity)
            elif "event=reply_render_confirmed" in line or "event=external_reply_confirmed" in line:
                delivered.add(identity)
            elif "event=eligible_direct_reply" in line:
                fields = dict(re.findall(r"\b(build_id|configuration_id|channel|actor_role)=([^ ]+)", line))
                # Only admitted requests emit eligibility, including a permitted first bot answer.
                stamp = datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                eligible[identity] = {"request_id": identity, "started_at": stamp.isoformat(),
                    **{key: value for key, value in fields.items() if value != "None"}}
            elif "runtime_metrics" in metadata:
                if metadata["runtime_metrics"].get("result_status") != "duplicate":
                    requests[identity] = metadata["runtime_metrics"]
    for identity, start in {**accepted, **eligible}.items():
        if identity not in requests:
            # An ingress with no terminal receipt remains in the denominator after timeout.
            started = datetime.fromisoformat(start["started_at"])
            overdue = (now - started).total_seconds() >= (start.get("request_timeout_seconds") or 600)
            requests[identity] = {**start, "result_status": "unverified" if overdue else "pending",
                                  "response_status": "unverified", "missing_runtime_receipt": True}
    groups = defaultdict(list)
    pending = 0
    manual_replays = Counter()
    for identity, row in requests.items():
        if identity.endswith(":maintenance") or row.get("route_source") == "internal_activity":
            continue
        if identity.startswith("external:") and identity not in eligible:
            continue
        if identity not in accepted and identity not in eligible:
            continue
        if row.get("source_request_id") and row["source_request_id"] != identity:
            manual_replays[row.get("result_status", "unknown")] += 1
            continue
        build = row.get("build_id") or "unknown_build"
        if build_id and build != build_id:
            continue
        if row.get("result_status") == "pending":
            pending += 1
            continue
        profile = row.get("configuration_id") or "unknown_configuration"
        groups[(build, profile)].append((identity, row))
    output = []
    for (build, profile), rows in sorted(groups.items()):
        rows.sort(key=lambda pair: pair[1].get("started_at", ""))
        window = rows[-500:]
        statuses = Counter(row.get("result_status", "unknown") for _, row in rows)
        def confirmed(pair):
            identity, row = pair
            return (identity in delivered and row.get("result_status") == "completed"
                    and row.get("response_status") == "succeeded" and not row.get("deterministic_fallback_used"))
        def stage_confirmed(pair):
            identity, row = pair
            return confirmed(pair) or (identity in delivered and row.get("result_status") == "waiting_for_permission"
                                      and row.get("response_status") == "waiting_for_permission")
        verified, recent = sum(map(confirmed, rows)), sum(map(confirmed, window))
        stages, recent_stages = sum(map(stage_confirmed, rows)), sum(map(stage_confirmed, window))
        first_stages = sum(stage_confirmed(pair) and pair[0] not in repairs for pair in rows)
        unified = sum(bool(row.get("unified_reply")) for _, row in rows)
        dated = [datetime.fromisoformat(row["started_at"]) for _, row in rows if row.get("started_at")]
        days = (max(dated)-min(dated)).total_seconds()/86400 if len(dated)>1 else 0
        calls = Counter(row.get("foreground_llm_calls", row.get("llm_call_count", "unknown")) for _, row in rows)
        kinds = Counter("images" if row.get("has_images") else "decision" if row.get("decision_used") else
                        "tool" if row.get("tool_call_count") else "chat" for _, row in rows)
        timings = {}
        for field in ("total_ms", "context_build_ms", "session_persist_ms", "response_packaging_ms", "ttfr_ms"):
            values = sorted(row[field] for _, row in rows if isinstance(row.get(field), (int, float)))
            timings[field] = {"reported": len(values), "p95": values[ceil(len(values)*.95)-1] if values else None}
        output.append({"build_id": build, "configuration_id": profile, "requests": len(rows), "statuses": dict(statuses),
            "missing_runtime_receipts": sum(bool(row.get("missing_runtime_receipt")) for _, row in rows),
            "delivery_confirmed": sum(identity in delivered for identity, _ in rows), "verified_completed": verified,
            "reported_completed_rate": round(statuses["completed"]/len(rows), 4),
            "unverified_completed": sum(row.get("result_status")=="completed" and identity not in delivered for identity,row in rows),
            "confirmed_completion_ratio": round(verified/len(rows), 4),
            "confirmed_current_stage_ratio": round(stages/len(rows), 4),
            "permission_stage_confirmed": stages-verified,
            "delivery_evidence_coverage": round(sum(identity in delivered for identity,_ in rows)/len(rows), 4),
            "body_repairs": sum(identity in repairs for identity, _ in rows),
            "first_reply_stage_confirmed_ratio": round(first_stages/len(rows), 4),
            "recent_500_requests": len(window), "recent_500_confirmed_ratio": round(recent/len(window), 4),
            "observation_days": round(days, 3), "foreground_call_distribution": dict(calls),
            "unified_requests": unified,
            "delivery_window": "pending" if build=="unknown_build" or profile=="unknown_configuration" or len(rows)<500 or days<7
                or stages/len(rows)<.98 or recent_stages/len(window)<.98 or first_stages/len(rows)<.98
                or unified<len(rows) else "candidate_window_met",
            "release_acceptance": "pending_business_review",
            "channels": dict(Counter(row.get("channel") or "unknown" for _,row in rows)), "task_kinds": dict(kinds),
            "timings_ms": timings,
            "scope": "Confirmed completion is a delivery-evidence lower bound; semantics, necessary persistence and per-channel samples require real review."})
    return {"builds": output, "metric_parse_errors": parse_errors, "pending_requests": pending, "manual_replays_not_added_to_denominator": dict(manual_replays),
            "model_requests_sent": 0, "external_messages_sent": 0, "production_data_modified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-directory", default=".zhaoxi/logs")
    parser.add_argument("--build-id")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit(sorted(Path(args.log_directory).glob("zhaoxi.log*")), args.build_id)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()