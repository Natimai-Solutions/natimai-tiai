"""The approval mails' texts (``approval_mail.py``), in French and in English.

Pinned word for word by ``tests/test_mail_languages.py``
(``tests/data/mail_texts.json``).
"""

from dataclasses import dataclass

from app.features.user.models import Language


@dataclass(frozen=True)
class ApprovalMailTexts:
    # What is asked, by command type; ``{package}`` for a deployment.
    actions: dict[str, str]
    # The target as asked, by kind; ``{value}`` its domain, site, status,
    # room or building.
    targets: dict[str, str]
    subject_request: str
    intro_command: str
    intro_schedule: str
    threshold: str
    expires: str
    decide: str
    footer_request: str
    subject_approved: str
    subject_rejected: str
    subject_expired: str
    subject_failed: str
    request_command: str
    request_schedule: str
    approved: str
    approved_counts: str
    approved_schedule: str
    rejected: str
    note: str
    expired: str
    failed: str
    causes: dict[str, str]
    open_page: str
    footer_outcome: str


FR = ApprovalMailTexts(
    actions={
        "reboot": "Redémarrer",
        "shutdown": "Éteindre",
        "wu_install": "Installer les mises à jour Windows",
        "wu_install_full": "Installer toutes les mises à jour Windows",
        "wu_reset": "Réinitialiser Windows Update",
        "spooler_reset": "Réinitialiser le spouleur d'impression",
        "dism_restore_health": "Réparer l'image Windows (DISM)",
        "dism_component_cleanup": "Nettoyer les composants Windows (DISM)",
        "package_install": "Installer le paquet {package}",
        "package_uninstall": "Désinstaller le paquet {package}",
    },
    targets={
        "machines": "une liste de postes",
        "all": "tout le parc",
        "domain": "le domaine « {value} »",
        "location": "l'emplacement « {value} »",
        "status": "les postes à l'état « {value} »",
        "room": "la salle « {value} »",
        "building": "le bâtiment « {value} »",
    },
    subject_request="{project} — Approbation demandée : {action} sur {count} postes",
    intro_command="{requested_by} demande « {action} » sur {count} postes ({target}).",
    intro_schedule=(
        "{requested_by} a enregistré la planification « {name} » : « {action} » "
        "sur {count} postes ({target})."
    ),
    threshold=(
        "Au-delà de {threshold} postes, une action à risque attend l'accord d'un "
        "second compte."
    ),
    expires="Sans décision, la demande expire le {expires} (UTC).",
    decide="L'approuver ou la refuser : {url}",
    footer_request=(
        "Vous recevez ce message parce que votre compte peut approuver cette demande."
    ),
    subject_approved="{project} — Votre demande a été approuvée",
    subject_rejected="{project} — Votre demande a été refusée",
    subject_expired="{project} — Votre demande a expiré",
    subject_failed="{project} — Votre demande a échoué",
    request_command="Votre demande « {action} » sur {count} postes",
    request_schedule="Votre planification « {name} » ({action}, {count} postes)",
    approved="{request} a été approuvée par {decided_by}.",
    approved_counts=(
        "Commandes envoyées : {created} ; postes qui l'avaient déjà : {skipped} ; "
        "postes laissés de côté : {left_out}."
    ),
    approved_schedule="Elle est active et s'exécutera à ses dates.",
    rejected="{request} a été refusée par {decided_by}.",
    note="Motif : {note}",
    expired="{request} a expiré sans décision : rien n'a été envoyé.",
    failed="{request} n'a pas pu être approuvée : {cause} Rien n'a été envoyé.",
    causes={
        "author_gone": "votre compte n'existe plus.",
        "author_inactive": "votre compte est désactivé.",
        "permission_lost": "votre compte n'a plus le droit « {permission} ».",
        "package_gone": "le paquet a été supprimé.",
        "package_changed": "le paquet a été modifié depuis la demande.",
        "nothing_left": "aucun des postes n'est encore dans votre portée.",
        "in_past": "sa date d'exécution est passée.",
        "forbidden_window": "elle tomberait dans une plage interdite.",
        "package.retired": "le paquet a été retiré.",
        "package.not_ready": "le paquet ne peut pas être déployé en l'état.",
        "package.not_found": "le paquet a été supprimé.",
    },
    open_page="Voir vos demandes : {url}",
    footer_outcome="Vous recevez ce message parce que vous êtes l'auteur de cette demande.",
)

EN = ApprovalMailTexts(
    actions={
        "reboot": "Restart",
        "shutdown": "Shut down",
        "wu_install": "Install Windows updates",
        "wu_install_full": "Install all Windows updates",
        "wu_reset": "Reset Windows Update",
        "spooler_reset": "Reset the print spooler",
        "dism_restore_health": "Repair the Windows image (DISM)",
        "dism_component_cleanup": "Clean up Windows components (DISM)",
        "package_install": "Install the package {package}",
        "package_uninstall": "Uninstall the package {package}",
    },
    targets={
        "machines": "a list of computers",
        "all": "the whole fleet",
        "domain": "the domain “{value}”",
        "location": "the location “{value}”",
        "status": "the computers in state “{value}”",
        "room": "the room “{value}”",
        "building": "the building “{value}”",
    },
    subject_request="{project} — Approval requested: {action} on {count} computers",
    intro_command=(
        "{requested_by} asks for “{action}” on {count} computers ({target})."
    ),
    intro_schedule=(
        "{requested_by} saved the schedule “{name}”: “{action}” on {count} "
        "computers ({target})."
    ),
    threshold=(
        "Above {threshold} computers, an action at risk waits for a second "
        "account's approval."
    ),
    expires="Without a decision, the request expires on {expires} (UTC).",
    decide="Approve or reject it: {url}",
    footer_request=(
        "You receive this message because your account can approve this request."
    ),
    subject_approved="{project} — Your request was approved",
    subject_rejected="{project} — Your request was rejected",
    subject_expired="{project} — Your request expired",
    subject_failed="{project} — Your request failed",
    request_command="Your request “{action}” on {count} computers",
    request_schedule="Your schedule “{name}” ({action}, {count} computers)",
    approved="{request} was approved by {decided_by}.",
    approved_counts=(
        "Commands sent: {created}; computers that already had it: {skipped}; "
        "computers left out: {left_out}."
    ),
    approved_schedule="It is active and will run at its dates.",
    rejected="{request} was rejected by {decided_by}.",
    note="Reason: {note}",
    expired="{request} expired without a decision: nothing was sent.",
    failed="{request} could not be approved: {cause} Nothing was sent.",
    causes={
        "author_gone": "your account no longer exists.",
        "author_inactive": "your account is deactivated.",
        "permission_lost": "your account no longer holds “{permission}”.",
        "package_gone": "the package was deleted.",
        "package_changed": "the package changed since the request.",
        "nothing_left": "none of the computers is in your scope any more.",
        "in_past": "its run date is past.",
        "forbidden_window": "it would run inside a forbidden window.",
        "package.retired": "the package was retired.",
        "package.not_ready": "the package cannot be deployed as it stands.",
        "package.not_found": "the package was deleted.",
    },
    open_page="See your requests: {url}",
    footer_outcome="You receive this message because you made this request.",
)

TEXTS: dict[Language, ApprovalMailTexts] = {Language.FR: FR, Language.EN: EN}
