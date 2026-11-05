from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Autenticação por e-mail (case-insensitive). Usuários inativos/bloqueados são recusados."""

    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        User = get_user_model()
        login = (email or username or kwargs.get(User.USERNAME_FIELD) or "").strip()
        if not login or password is None:
            return None
        try:
            user = User.objects.get(email__iexact=login)
        except User.DoesNotExist:
            User().set_password(password)  # mitiga timing attack
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
