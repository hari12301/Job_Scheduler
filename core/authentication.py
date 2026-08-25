from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from core.models import APIKey

class APIKeyAuthentication(BaseAuthentication):
    """
    Authenticates requests using the 'X-API-Key' header or 'Authorization: Bearer <key>'.
    """
    def authenticate(self, request):
        api_key_header = request.headers.get('X-API-Key')
        if not api_key_header:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                api_key_header = auth_header[7:].strip()

        if not api_key_header:
            return None  # Fall back to other authentication classes

        key_obj = APIKey.verify_key(api_key_header)
        if not key_obj:
            raise AuthenticationFailed("Invalid or inactive API Key.")

        # Attach authenticated project and API key to request
        request.project = key_obj.project
        request.api_key = key_obj

        # Return (User, Auth) tuple - mock or admin user for API key
        return (None, key_obj)

