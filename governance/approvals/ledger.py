import json
import os
import time
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

# Configuration
LEDGER_DIR = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))) / "governance" / "approvals"
STATE_FILE = LEDGER_DIR / "approval_state.json"
AUDIT_FILE = LEDGER_DIR / "approval_audit.jsonl"

class ApprovalLedger:
    """
    Approval State Machine for KENSEI Triage.
    Manages the lifecycle of triage requests from PENDING to APPROVED/REJECTED/AMENDED.
    """
    def __init__(self):
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_state(self):
        STATE_FILE.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def _log_audit(self, triage_id: str, action: str, actor: str, reason: Optional[str] = None, metadata: Optional[Dict] = None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "triage_id": triage_id,
            "action": action,
            "actor": actor,
            "reason": reason,
            "metadata": metadata or {}
        }
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def submit_for_approval(self, triage_id: str, summary: str, fingerprint: str, routing: Dict[str, str], metadata: Optional[Dict] = None) -> Dict:
        """Initializes a triage request in the PENDING state."""
        if triage_id in self.state:
            return {"status": "error", "message": f"Triage ID {triage_id} already exists"}

        entry = {
            "triage_id": triage_id,
            "summary": summary,
            "fingerprint": fingerprint,
            "routing": routing, # {board: ..., assignee: ...}
            "metadata": metadata or {},
            "status": "PENDING",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.state[triage_id] = entry
        self._save_state()
        self._log_audit(triage_id, "SUBMIT", "system", reason="Triage request submitted for approval")
        return {"status": "ok", "triage_id": triage_id}

    def process_action(self, triage_id: str, action: str, actor: str, reason: Optional[str] = None) -> Tuple[bool, str]:
        """
        Transitions the state of a request.
        Actions: 'approve', 'reject', 'amend'
        """
        if triage_id not in self.state:
            return False, f"Triage ID {triage_id} not found in ledger"

        req = self.state[triage_id]
        current_status = req["status"]

        if action == "approve":
            if current_status not in ["PENDING", "AMENDING"]:
                return False, f"Cannot approve request in state {current_status}"
            
            req["status"] = "APPROVED"
            req["approved_at"] = datetime.now(timezone.utc).isoformat()
            req["approved_by"] = actor
            self._log_audit(triage_id, "APPROVE", actor, reason)
            
        elif action == "reject":
            if current_status not in ["PENDING", "AMENDING"]:
                return False, f"Cannot reject request in state {current_status}"
            
            req["status"] = "REJECTED"
            req["rejected_at"] = datetime.now(timezone.utc).isoformat()
            req["rejected_by"] = actor
            self._log_audit(triage_id, "REJECT", actor, reason)
            
        elif action == "amend":
            if current_status not in ["PENDING", "AMENDING"]:
                return False, f"Cannot amend request in state {current_status}"
            
            req["status"] = "AMENDING"
            req["amended_at"] = datetime.now(timezone.utc).isoformat()
            req["amended_by"] = actor
            self._log_audit(triage_id, "AMEND", actor, reason)
        else:
            return False, f"Unknown action: {action}"

        req["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_state()
        return True, f"Request {triage_id} transitioned to {req['status']}"

    def get_request(self, triage_id: str) -> Optional[Dict]:
        return self.state.get(triage_id)

def generate_fingerprint(source_text: str) -> str:
    """Generates a stable fingerprint for a source to detect duplicates."""
    return hashlib.sha256(source_text.strip().lower().encode()).hexdigest()
