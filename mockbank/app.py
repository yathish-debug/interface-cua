"""MockBank — a fake legacy core-banking servicing console.

Flow: member lookup -> member detail (savings balance) -> open sub-account -> confirmation.
Deliberately old-school table markup, no test IDs. This is our stand-in for a real
bank app, so we fully control the runtime error/exceptional states.
"""
import os
import random
import string

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="MockBank Core Console")
templates = Jinja2Templates(directory="mockbank/templates")

# Fake in-memory "core banking" records.
MEMBERS = {
    "12345": {"name": "Asha Rao",    "savings": "4,250.00",  "status": "Active"},
    "23456": {"name": "Vikram Nair", "savings": "18,900.50", "status": "Active"},
    "34567": {"name": "Priya Menon", "savings": "760.25",    "status": "Frozen"},
}


def inject(condition: str) -> bool:
    """Error-injection switch, driven by the INJECT env var.
    Lets us force a specific runtime condition to test replay later."""
    return os.getenv("INJECT", "").lower() == condition


@app.get("/", response_class=HTMLResponse)
def home(request: Request, error: str | None = None):
    return templates.TemplateResponse(request, "home.html", {"error": error})


@app.post("/lookup", response_class=HTMLResponse)
def lookup(request: Request, member_id: str = Form(default="")):
    member_id = member_id.strip()
    if not member_id:  # validation error
        return templates.TemplateResponse(
            request, "home.html", {"error": "Member ID is required."}, status_code=400
        )
    if member_id not in MEMBERS:  # record-not-found = business outcome, NOT a crash
        return templates.TemplateResponse(
            request, "not_found.html", {"member_id": member_id}
        )
    return RedirectResponse(url=f"/member/{member_id}", status_code=303)


@app.get("/member/{member_id}", response_class=HTMLResponse)
def member_detail(request: Request, member_id: str):
    if inject("timeout"):  # session timeout, forced via INJECT=timeout
        return templates.TemplateResponse(request, "timeout.html", {}, status_code=440)
    member = MEMBERS.get(member_id)
    if not member:
        return templates.TemplateResponse(
            request, "not_found.html", {"member_id": member_id}
        )
    return templates.TemplateResponse(
        request, "member.html", {"member_id": member_id, "member": member}
    )


@app.get("/member/{member_id}/open-subaccount", response_class=HTMLResponse)
def open_subaccount_form(request: Request, member_id: str):
    member = MEMBERS.get(member_id)
    if not member:
        return templates.TemplateResponse(
            request, "not_found.html", {"member_id": member_id}
        )
    return templates.TemplateResponse(
        request, "open_subaccount.html",
        {"member_id": member_id, "member": member, "error": None},
    )


@app.post("/member/{member_id}/open-subaccount", response_class=HTMLResponse)
def open_subaccount_submit(
    request: Request,
    member_id: str,
    account_type: str = Form(default=""),
    initial_deposit: str = Form(default=""),
):
    member = MEMBERS.get(member_id)
    if not member:
        return templates.TemplateResponse(
            request, "not_found.html", {"member_id": member_id}
        )
    if not account_type or not initial_deposit:  # validation error
        return templates.TemplateResponse(
            request, "open_subaccount.html",
            {"member_id": member_id, "member": member,
             "error": "Account type and initial deposit are both required."},
            status_code=400,
        )
    if member["status"] == "Frozen":  # permission-style business outcome
        return templates.TemplateResponse(
            request, "open_subaccount.html",
            {"member_id": member_id, "member": member,
             "error": "This member is frozen and cannot open new accounts."},
            status_code=403,
        )
    sub_no = "SA-" + "".join(random.choices(string.digits, k=8))
    return templates.TemplateResponse(
        request, "confirmation.html",
        {"member_id": member_id, "member": member,
         "account_type": account_type, "initial_deposit": initial_deposit,
         "sub_account_number": sub_no},
    )