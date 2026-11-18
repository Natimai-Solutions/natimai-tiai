"""The language a mail is written in (plan ``dev/plan-console-bilingue.md``, I4).

Mail is the one text the server still writes itself: it leaves without a
browser to word it. Each mail is written in its reader's language — the one
their account chose in « Mon compte », else ``DEFAULT_LANGUAGE`` (French unless
the deployment says otherwise, so an installation that sets nothing sends the
mail it always sent).

The texts themselves live beside each mail, in a small catalogue per mail
(``digest_texts``, ``tasks_texts``…): the French and the English side by
side, the English typed against the same fields so that a text without its
translation does not type-check.
"""

from app.core.config import settings
from app.features.user.models import Language


def mail_language(choice: str | None) -> Language:
    """The language of a mail to an account whose stored choice is ``choice``.

    No choice — or a value written by hand that is not a language, read as no
    choice like ``/auth/me`` does — means the deployment's default.
    """
    if choice in set(Language):
        return Language(choice)
    return Language(settings.DEFAULT_LANGUAGE)


def texts_for[T](catalogue: dict[Language, T], language: Language | None) -> T:
    """A mail's catalogue in ``language`` — ``None`` being the default one."""
    return catalogue[language or mail_language(None)]


def plural(n: int, one: str, many: str) -> str:
    """``n`` and the English noun that agrees with it: « 1 computer »,
    « 3 computers ». French keeps its « poste(s) », as the mail always wrote."""
    return f"{n} {one if n == 1 else many}"
