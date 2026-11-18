"""The texts of the mail about somebody's tasks (``tasks.py``), in French and
in English: the assignment of a verification, the « VOS TÂCHES » block of the
digest, the weekly maintenance reminder.

The French is the mail as it has always read, word for word — pinned by
``tests/test_mail_languages.py``.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.features.notification.language import plural
from app.features.user.models import Language


def _computers(n: int) -> str:
    return plural(n, "computer", "computers")


@dataclass(frozen=True)
class TasksTexts:
    # --- a verification handed to somebody
    check_subject_one: Callable[[str, str], str]
    check_intro_one: Callable[[str, str], str]
    check_subject_many: Callable[[str, int], str]
    check_intro_many: Callable[[str, int], str]
    instructions: str
    # « … et N autre(s) », after the indentation of the list it ends.
    more: Callable[[int], str]
    tasks_link: Callable[[str], str]
    check_footer: str
    # --- the « VOS TÂCHES » block
    your_tasks: str
    checks_assigned: Callable[[int], str]
    maintenance_summary: Callable[[int, int], str]
    room_line: Callable[[str, int, int], str]
    loose_line: Callable[[str, str], str]
    overdue: str
    due_soon: str
    see: Callable[[str], str]
    # --- the weekly reminder
    reminder_subject: Callable[[str, str], str]
    reminder_intro: str
    reminder_footer: str


FR = TasksTexts(
    check_subject_one=lambda project, name: (
        f"{project} — vérification demandée : {name}"
    ),
    check_intro_one=lambda who, name: (
        f"{who} vous demande de vérifier le poste {name}."
    ),
    check_subject_many=lambda project, n: (
        f"{project} — vérification demandée sur {n} postes"
    ),
    check_intro_many=lambda who, n: f"{who} vous demande de vérifier {n} postes.",
    instructions="Consignes :",
    more=lambda n: f"… et {n} autre(s)",
    tasks_link=lambda link: f"Vos tâches : {link}",
    check_footer=(
        "Vous recevez ce message parce qu'une vérification vous a été affectée. "
        "Réglez vos e-mails dans la console, page « Mon compte »."
    ),
    your_tasks="VOS TÂCHES",
    checks_assigned=lambda n: f"  Vérifications qui vous sont affectées : {n}",
    maintenance_summary=lambda overdue, due_soon: (
        f"  Maintenances dont vous êtes responsable : {overdue} poste(s) en retard, "
        f"{due_soon} à échéance"
    ),
    room_line=lambda place, overdue, due_soon: (
        f"    • {place} — {overdue} en retard, {due_soon} à échéance"
    ),
    loose_line=lambda name, state: f"    • {name} (sans salle) — {state}",
    overdue="en retard",
    due_soon="à échéance",
    see=lambda link: f"  Voir : {link}",
    reminder_subject=lambda project, date: f"{project} — vos maintenances au {date}",
    reminder_intro="Rappel hebdomadaire de ce qui vous attend.",
    reminder_footer=(
        "Vous recevez ce message parce que vous êtes responsable de la maintenance "
        "de salles ou de postes. Réglez vos e-mails dans la console, page « Mon compte »."
    ),
)

EN = TasksTexts(
    check_subject_one=lambda project, name: f"{project} — check requested: {name}",
    check_intro_one=lambda who, name: f"{who} asks you to check the computer {name}.",
    check_subject_many=lambda project, n: (
        f"{project} — check requested on {n} computers"
    ),
    check_intro_many=lambda who, n: f"{who} asks you to check {n} computers.",
    instructions="Instructions:",
    more=lambda n: f"… and {n} more",
    tasks_link=lambda link: f"Your tasks: {link}",
    check_footer=(
        "You receive this message because a check was assigned to you. "
        "Choose your e-mails in the console, under My account."
    ),
    your_tasks="YOUR TASKS",
    checks_assigned=lambda n: f"  Checks assigned to you: {n}",
    maintenance_summary=lambda overdue, due_soon: (
        f"  Maintenance you own: {_computers(overdue)} overdue, {due_soon} due soon"
    ),
    room_line=lambda place, overdue, due_soon: (
        f"    • {place} — {overdue} overdue, {due_soon} due soon"
    ),
    loose_line=lambda name, state: f"    • {name} (no room) — {state}",
    overdue="overdue",
    due_soon="due soon",
    see=lambda link: f"  View: {link}",
    reminder_subject=lambda project, date: f"{project} — your maintenance on {date}",
    reminder_intro="Weekly reminder of what is waiting for you.",
    reminder_footer=(
        "You receive this message because you own the maintenance of rooms or "
        "computers. Choose your e-mails in the console, under My account."
    ),
)

TEXTS: dict[Language, TasksTexts] = {Language.FR: FR, Language.EN: EN}
