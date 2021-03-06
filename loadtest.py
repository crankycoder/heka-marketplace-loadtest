import base64
from Cookie import Morsel
import json
import os
import random
import re
import unicodedata
import uuid
import urllib2

from funkload.utils import Data
from funkload.FunkLoadTestCase import FunkLoadTestCase
from webunit.utility import Upload

from util import read_password

USER_AGENT = 'Mozilla/5.0 (Android; Mobile; rv:18.0) Gecko/18.0 Firefox/18.0'
CSRF_REGEX = re.compile(r'.*csrfmiddlewaretoken\' value=\'(.*)\'')
WEBAPP = 'http://%s.webapp.lolnet.org/manifest.webapp'
RE_NAME = '<input name="display_name".*?value="(.*?)" '
RE_NAME = re.compile(RE_NAME, re.M | re.I)

HERE = os.path.abspath(os.path.dirname(__name__))
GITHUB =  'https://raw.github.com/mozilla/marketplace-loadtest/master/'

ICON = os.path.join(HERE, 'icon.png')
if not os.path.exists(ICON):
    with open(ICON, 'wb') as f:
       f.write(urllib2.urlopen(GITHUB + 'icon.png').read())


SCREENSHOT = os.path.join(HERE, 'screenshot.png')
if not os.path.exists(SCREENSHOT):
    with open(SCREENSHOT, 'wb') as f:
       f.write(urllib2.urlopen(GITHUB + 'screenshot.png').read())


class HekaMarketplaceTest(FunkLoadTestCase):

    def __init__(self, *args, **kwargs):
        super(HekaMarketplaceTest, self).__init__(*args, **kwargs)

        self.root = self.conf_get('main', 'url')
        self.lang = 'en-US'
        self._apps = None
        self._categories = None

    def setBasicAuth(self, username, password):
        '''Set the Basic authentication information to the given username
        and password.
        '''
        self._browser.authinfo = base64.b64encode('%s:%s' % (username,
            password)).strip()
        self._authinfo = '%s:%s@' % (username, password)

    def get(self, url, *args, **kwargs):
        """Do a GET request with the given URL.

        This call sets the Accept-Languages header and ask funkload to not
        follow img/css/js links.
        """
        # when GETing an URL, we don't want to follow the links (img, css etc)
        # as they could be done on the fly by javascript in an obstrusive way.
        # we also prepend the domain (self.root) to the get calls in this
        # method.
        self.setHeader('Accept-Languages', self.lang)
        self.setHeader('User-Agent', USER_AGENT)
        return super(HekaMarketplaceTest, self).get(self.root + url,
                                                load_auto_links=False,
                                                *args, **kwargs)

    def post(self, url, *args, **kwargs):
        return super(HekaMarketplaceTest, self).post(self.root + url,
            load_auto_links=False, *args, **kwargs)

    @property
    def apps(self):
        if self._apps is None:
            self._apps = self.get_apps()
            if len(self._apps) > 4:
                self._apps = random.sample(self._apps, 4)
        return self._apps

    def get_apps(self):
        """Get the list of apps from the marketplace API"""
        resp = self.get('/api/apps/search/')
        content = json.loads(resp.body)
        return [p['slug'] for p in content['objects']]

    @property
    def categories(self):
        if self._categories is None:
            self._categories = self.get_categories()
            if len(self._categories) > 4:
                self._categories = random.sample(self._categories)
        return self._categories

    def get_categories(self):
        """Get all the categories from the marketplace API"""
        resp = self.get('/en-US/api/apps/category/')
        cats = json.loads(resp.body)['objects']
        return [slugify(c['name']) for c in cats]

    def query_search(self):
        # do a search with the name of the selected apps
        for app in self.apps:
            self.search_app(query=app)

    def query_apps_detail(self):
        for app in self.apps:
            self.get('/app/{app}/'.format(app=app))

    def query_categories(self):
        for category in self.categories:
            self.get('/apps/{category}'.format(category=category))

    def view_homepage(self):
        ret = self.get('/')
        self.assertTrue('Categories' in ret.body)

    def search_app(self, query='twi'):
        # search for some non-empty string, to make a realistic and not
        # too expensive query
        ret = self.get('/search/?q=%s' % query)
        self.assertTrue('Search Results' in ret.body)

    def install_free_app(self):
        # all the logic for free apps is client side - as long as the
        # manifest url is in the page, the process should succeed
        if not self.apps:
            return
        ret = self.get('/app/%s' % random.choice(self.apps))
        self.assertTrue('data-manifest_url="' in ret.body)

    def rate_app(self, rating=3, comment=None):
        if not self.apps:
            return
        appname = random.choice(self.apps)
        url = '/app/%s/reviews/add' % appname
        ret = self.get(url)

        if comment is None:
            body = 'This app is the cool thing'
        else:
            body = comment

        # adding a unique id
        body += ' ' + uuid.uuid1().hex
        rating = str(rating)
        params = [['body', body],
                  ['rating', rating]]

        add_csrf_token(ret, params)
        self.post(url, params=params, ok_codes=[200, 302])

        # XXX this is done async so we can't check now
        # I am not sure what's the best thing to do
        #
        # let's see if our review made it
        #ret = self.get('/app/%s/reviews' % appname)
        #self.assert_(body in ret.body)

    def edit_details(self):
        # since we can have other tests doing this in
        # parallel, we'll just check that it was changed
        ret = self.get('/settings')
        original = RE_NAME.findall(ret.body)
        if len(original) == 0:
            original = 'UNKNOWN'
        else:
            original = original[0]
        display = uuid.uuid1().hex
        params = [['display_name', display]]
        add_csrf_token(ret, params)
        self.post('/settings', params=params)

        # checking the result
        ret = self.get('/settings')
        self.assert_(original not in ret.body,
                     'Found %r for the display' % original)

    def submit_app(self):
        # try to submit an app
        ret = self.get('/developers/submit/app', ok_codes=[200, 302])

        # generate a random web-app manifest
        random_id = uuid.uuid1().hex
        manifest_url = WEBAPP % random_id

        # we need to accept the TOS once per user
        if 'read_dev_agreement' in ret.body:
            params = [['read_dev_agreement', 'True']]
            add_csrf_token(ret, params)
            ret = self.post(ret.url, params=params)

        # submit the manifest
        params = [['manifest', manifest_url]]
        add_csrf_token(ret, params)
        ret = self.post('/developers/upload-manifest', params=params)
        data = json.loads(ret.body)
        validation = data['validation']
        app_exists = False

        if isinstance(validation, dict) and 'messages' in validation:
            messages = [m['message'] for m in data['validation']['messages']]
            app_exists = 'already' in ' '.join(messages)

        # we should be able to test editing the app
        if app_exists:
            return

        if isinstance(validation, dict) and 'errors' in validation:
            self.assertEqual(data['validation']['errors'], 0, data)

        # now we can submit the app basics, first load the form again
        ret = self.get('/developers/submit/app/manifest')
        params = [['upload', data['upload']],
                  ['free', 'free-os'],
                  ['free', 'free-desktop'],
                  ['free', 'free-phone'],
                  ['free', 'free-tablet']]
        add_csrf_token(ret, params)
        ret = self.post('/developers/submit/app/manifest', params=params)
        self.assertTrue('/submit/app/details/' in ret.url, ret.url)
        app_slug = ret.url.split('/')[-1]

        # upload icon
        params = [['upload_image', Upload(ICON)]]
        add_csrf_token(ret, params)
        ret = self.post('/developers/app/%s/upload_icon' % app_slug,
            params=params)
        data = json.loads(ret.body)
        self.assertEqual(len(data['errors']), 0, data)
        icon_hash = data['upload_hash']

        # upload screenshot
        ret = self.get('/developers/submit/app/details/%s' % app_slug)
        params = [['upload_image', Upload(SCREENSHOT)]]
        add_csrf_token(ret, params)
        ret = self.post('/developers/app/%s/upload_image' % app_slug,
            params=params)
        data = json.loads(ret.body)
        self.assertEqual(len(data['errors']), 0, data)
        screenshot_hash = data['upload_hash']

        # fill in some more app details
        ret = self.get('/developers/submit/app/details/%s' % app_slug)
        params = [
            ['slug', app_slug],
            ['slug_en-us', app_slug],
            ['name_en-us', app_slug],
            ['summary_en-us', 'HA Test web app'],
            ['privacy_policy_en-us', 'We sell all your data!'],
            ['support_email_en-us', 'marketplace-devs@mozilla.com'],
            ['icon_upload_hash', icon_hash],
            ['icon_upload_hash_en-us', icon_hash],
            ['icon_type', 'image/png'],
            ['icon_type_en-us', 'image/png'],
            ['categories', '167'],
            ['categories_en-us', '167'],
            ['files-0-position', '0'],
            ['files-0-position_en-us', '0'],
            ['files-0-upload_hash', screenshot_hash],
            ['files-0-upload_hash_en-us', screenshot_hash],
            ['files-0-unsaved_image_type', 'image/png'],
            ['files-0-unsaved_image_type_en-us', 'image/png'],
            ['files-TOTAL_FORMS', '1'],
            ['files-TOTAL_FORMS_en-us', '1'],
            ['files-INITIAL_FORMS', '0'],
            ['files-INITIAL_FORMS_en-us', '0'],
            ['files-MAX_NUM_FORMS', '1'],
            ['files-MAX_NUM_FORMS_en-us', '1'],
        ]
        token = add_csrf_token(ret, params)
        if token:
            # work around creative code in app edit form
            params.append(['csrfmiddlewaretoken_en-us', token])

        # hack in the current_locale cookie
        cookies = self._browser.cookies
        morsel = Morsel()
        morsel.set('current_locale', 'en-us', 'en-us')
        for domain, value in cookies.items():
            value['/'].setdefault('current_locale', morsel)

        # fill details and submit
        ret = self.post(ret.url, params=params)

        # finally delete the app
        ret = self.get('/developers/app/%s/status' % app_slug)
        params = []
        add_csrf_token(ret, params)
        self.post('/developers/app/%s/delete' % app_slug, params=params)

    def test_anonymous(self):
        self.clearBasicAuth()
        self.view_homepage()
        self.search_app()
        self.query_search()
        self.query_categories()
        self.query_apps_detail()

    def test_end_user(self):
        self.setBasicAuth('enduser@mozilla.com', read_password())
        try:
            self.view_homepage()
            self.search_app()
            self.install_free_app()
            self.edit_details()
            self.rate_app()
        finally:
            self.clearBasicAuth()

    def test_developer(self):
        self.setBasicAuth('developer@mozilla.com', read_password())
        try:
            self.view_homepage()
            self.search_app()
            self.submit_app()
        finally:
            self.clearBasicAuth()

    def test_editor(self):
        # XXX not done yet
        # XXX we should delete some apps here too
        # so we don't grow the DB
        pass

    def test_marketplace(self):
        """ 
        Run :
            test_cef
        """
        #self.test_developer()
        #self.test_end_user()
        self.test_cef() 

    def test_cef(self): 
        """ 
        this should fire off statsd and cef messages by hitting the
        CSP report

        This requires that you have run:

            mysql> update waffle_sample_mkt set percent = 100 where name = 'csp-store-reports';

        in advance.
        """

        url = 'http://foo.com'
        jdata = json.dumps({'csp-report': {'document-uri': url}})

        self.post("/services/csp/report",
                          params=Data('application/json', jdata),
                                description="Call CSP API")


    def test_errors(self):
        # TODO: just POST to the divide by zero generate-admin page
        pass



def add_csrf_token(response, params):
    token = CSRF_REGEX.findall(response.body)
    if token:
        params.append(['csrfmiddlewaretoken', token[0]])
        return token[0]
    return None


def slugify(value):
    """This is the slugify from django, minus an hardcoded workaround"""
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(re.sub('[^\w\s-]', '', value).strip().lower())
    slugified = re.sub('[-\s]+', '-', value)

    # workaround for now
    if slugified == 'social-communications':
        return 'social'
    return slugified


if __name__ == '__main__':
    import unittest
    unittest.main()
