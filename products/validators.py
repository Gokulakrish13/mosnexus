"""
Custom password validators for enhanced security.
Implements OWASP password strength recommendations.
"""

# pylint: disable=missing-function-docstring,unused-argument
import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class PasswordStrengthValidator:
    """
    Validates that the password meets complexity requirements:
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    """

    def __init__(self, min_uppercase=1, min_lowercase=1, min_digits=1, min_special=1):
        self.min_uppercase = min_uppercase
        self.min_lowercase = min_lowercase
        self.min_digits = min_digits
        self.min_special = min_special

    def validate(self, password, user=None):
        errors = []

        if len(re.findall(r"[A-Z]", password)) < self.min_uppercase:
            errors.append(
                _("Password must contain at least %(min)d uppercase letter(s).") % {"min": self.min_uppercase}
            )

        if len(re.findall(r"[a-z]", password)) < self.min_lowercase:
            errors.append(
                _("Password must contain at least %(min)d lowercase letter(s).") % {"min": self.min_lowercase}
            )

        if len(re.findall(r"\d", password)) < self.min_digits:
            errors.append(_("Password must contain at least %(min)d digit(s).") % {"min": self.min_digits})

        special_chars = re.findall(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?`~]', password)
        if len(special_chars) < self.min_special:
            errors.append(
                _("Password must contain at least %(min)d special character(s) (!@#$%%^&*()_+-=[]{};':\"|,.<>/?`~).")
                % {"min": self.min_special}
            )

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return _(
            "Your password must contain at least %(uppercase)d uppercase letter(s), "
            "%(lowercase)d lowercase letter(s), %(digits)d digit(s), and "
            "%(special)d special character(s)."
        ) % {
            "uppercase": self.min_uppercase,
            "lowercase": self.min_lowercase,
            "digits": self.min_digits,
            "special": self.min_special,
        }


class NoRepeatingCharactersValidator:
    """
    Validates that the password doesn't contain excessive repeating characters.
    """

    def __init__(self, max_consecutive=3):
        self.max_consecutive = max_consecutive

    def validate(self, password, user=None):
        pattern = r"(.)\1{" + str(self.max_consecutive) + r",}"
        if re.search(pattern, password):
            raise ValidationError(
                _("Password cannot contain more than %(max)d consecutive repeating characters."),
                code="repeating_characters",
                params={"max": self.max_consecutive},
            )

    def get_help_text(self):
        return _("Your password cannot contain more than %(max)d consecutive repeating characters.") % {
            "max": self.max_consecutive
        }


class NoCommonPatternsValidator:
    """
    Validates that the password doesn't contain common weak patterns.
    """

    COMMON_PATTERNS = [
        r"12345",
        r"qwerty",
        r"password",
        r"abc123",
        r"letmein",
        r"welcome",
        r"admin",
        r"login",
    ]

    def validate(self, password, user=None):
        password_lower = password.lower()
        for pattern in self.COMMON_PATTERNS:
            if pattern in password_lower:
                raise ValidationError(
                    _('Password contains a common pattern that is not allowed: "%(pattern)s".'),
                    code="common_pattern",
                    params={"pattern": pattern},
                )

    def get_help_text(self):
        return _('Your password cannot contain common patterns like "password", "12345", "qwerty", etc.')
