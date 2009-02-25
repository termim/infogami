"""
Infogami read/write API.
"""
import web
import infogami
from infogami.utils import delegate
from infogami.utils.view import safeint
from infogami.infobase import client
import simplejson

hooks = {}        
def add_hook(name, cls):
    hooks[name] = cls

class api(delegate.page):
    path = "/api/(.*)"
    
    def delegate(self, suffix):
        # Have an option of setting content-type to text/plain
        i = web.input(_method='GET', text="false")
        if i.text.lower() == "false":
            web.header('Content-type', 'application/json')
        else:
            web.header('Content-type', 'text/plain')

        if suffix in hooks:
            method = web.ctx.method
            cls = hooks[suffix]
            m = getattr(cls(), method, None)
            if m:
                raise web.HTTPError('200 OK', {}, m())
            else:
                web.ctx.status = '405 Method Not Allowed'
        else:
            web.ctx.status = '404 Not Found'
            
    GET = POST = delegate

class infobase_request:
    def delegate(self):
        sitename = web.ctx.site.name
        path = web.lstrips(web.ctx.path, "/api")
        method = web.ctx.method
        data = web.input()
        
        conn = client.connect(**infogami.config.infobase_parameters)
        
        try:
            out = conn.request(sitename, path, method, data)
            return '{"status": "ok", "result": %s}' % out
        except client.ClientException, e:
            return '{"status": "fail", "message": "%s"}' % str(e)
    
    GET = delegate
    
    def POST(self):
        if not can_write():
            return '{"status": "fail", "message": "Permssion Denied"}'
        return self.delegate()

add_hook("get", infobase_request)
add_hook("things", infobase_request)
add_hook("versions", infobase_request)

# for internal use
add_hook("write", infobase_request)
add_hook("save_many", infobase_request)

def jsonapi(f):
    def g(*a, **kw):
        try:
            out = f(*a, **kw)
        except client.ClientException, e:
            raise web.HTTPError(e.status, {}, str(e))
        
        i = web.input(_method='GET', callback=None)
        
        if i.callback:
            out = '%s(%s)' % (i.callback, out)
            
        return delegate.RawText(out, content_type="application/json")
    return g
        
def request(path, method='GET', data=None):
    return web.ctx.site._conn.request(web.ctx.site.name, path, method=method, data=data)
    
class Forbidden(web.HTTPError):
    def __init__(self, msg=""):
        web.HTTPError.__init__(self, "403 Forbidden", {}, msg)
        
class BadRequest(web.HTTPError):
    def __init__(self, msg=""):
        web.HTTPError.__init__(self, "400 Bad Request", {}, msg)
        
def can_write():
    user = delegate.context.user and delegate.context.user.key
    usergroup = web.ctx.site.get('/usergroup/api')
    return usergroup and user in [u.key for u in usergroup.members]
    
class view(delegate.mode):
    encoding = "json"
    
    @jsonapi
    def GET(self, path):
        i = web.input(v=None)
        v = safeint(i.v, None)        
        data = dict(key=path, revision=v)
        return request('/get', data=data)
        
    @jsonapi
    def PUT(self, path):
        if not can_write():
            raise Forbidden("Permission Denied.")
            
        return request('/save' + path, 'POST', web.data())
        
def make_query(i, required_keys=None):
    """Removes keys starting with _ and limits the keys to required_keys, if it is specified.
    
    >>> make_query(dict(a=1, _b=2))
    {'a': 1}
    >>> make_query(dict(a=1, _b=2, c=3), required_keys=['a'])
    {'a': 1}
    """
    query = {}
    for k, v in i.items():
        if k.startswith('_'):
            continue
        if required_keys and k not in required_keys:
            continue
        if v == '':
            v = None
        query[k] = v
    return query
        
class history(delegate.mode):
    encoding = "json"

    @jsonapi
    def GET(self, path):
        query = make_query(web.input(), required_keys=['author', 'ip', 'offset', 'limit'])
        query['key'] = path
        query['sort'] = '-created'
        return request('/versions', data=dict(query=simplejson.dumps(query)))
        
class recentchanges(delegate.page):
    encoding = "json"
    
    @jsonapi
    def GET(self):
        i = web.input(query=None)
        query = i.pop('query')
        if not query:
            query = simplejson.dumps(make_query(i, required_keys=["key", "type", "author", "ip", "offset", "limit"]))
        return request('/versions', data=dict(query=query))

class query(delegate.page):
    encoding = "json"
    
    @jsonapi
    def GET(self):
        i = web.input(query=None)
        query = i.pop('query')
        if not query:
            query = simplejson.dumps(make_query(i))
        return request('/things', data=dict(query=query, details="true"))

class login(delegate.page):
    encoding = "json"
    path = "/account/login"
    
    def POST(self):
        try:
            d = simplejson.loads(web.data())
            web.ctx.site.login(d['username'], d['password'])
            web.setcookie(infogami.config.login_cookie_name, web.ctx.conn.get_auth_token())
        except Exception, e:
            raise BadRequest(str(e))
