"""Keep public profile-photo bytes reusable across session-cookie changes."""
from flask import request
from flask.sessions import SecureCookieSessionInterface


class PublicAvatarSessionInterface(SecureCookieSessionInterface):
    def save_session(self, app, session, response):
        public_photo = (
            request.endpoint == 'public_avatar_photo'
            and response.status_code == 200
            and response.mimetype in {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
            and response.cache_control.public
        )
        if public_photo and not session.modified and 'Set-Cookie' not in response.headers:
            # This route's bytes depend only on the public wallet/photo version.
            # Incidental rate-limit/auth reads must not add Vary: Cookie, nor
            # renew a permanent session cookie on an immutable image response.
            response.vary.discard('Cookie')
            return
        super().save_session(app, session, response)
        if public_photo:
            # Preserve real session changes and their cookies, but never allow
            # a response that writes identity cookies into a public cache.
            response.headers['Cache-Control'] = 'private, no-store'


def install(appmod):
    app = appmod.app
    if isinstance(app.session_interface, PublicAvatarSessionInterface):
        return
    if type(app.session_interface) is not SecureCookieSessionInterface:
        raise RuntimeError('Public avatar cache requires the standard cookie session interface')
    interface = PublicAvatarSessionInterface()
    interface.__dict__.update(app.session_interface.__dict__)
    app.session_interface = interface
