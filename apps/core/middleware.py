class SecurityHeadersMiddleware:
    """Cabeçalhos de segurança complementares aos do Django."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        if not request.path.startswith("/django-admin/"):
            response.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                "img-src 'self' data: blob: https:; "
                "style-src 'self' 'unsafe-inline'; "
                # Alpine.js avalia expressões em atributos e por isso precisa de 'unsafe-eval'.
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "font-src 'self'; "
                "connect-src 'self' https://viacep.com.br; "
                "frame-ancestors 'none'; "
                "form-action 'self' https://www.mercadopago.com.br https://sandbox.mercadopago.com.br; "
                "base-uri 'self'",
            )
        return response
