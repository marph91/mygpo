#
# This file is part of my.gpodder.org.
#
# my.gpodder.org is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# my.gpodder.org is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public
# License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with my.gpodder.org. If not, see <http://www.gnu.org/licenses/>.
#

from django.http import HttpResponse
from django.contrib.auth.models import User
from mygpo.api.opml import Importer, Exporter
from mygpo.api.models import Podcast, Device
from mygpo.api.backend import get_device
from datetime import datetime
from django.utils.datastructures import MultiValueDictKeyError
from django.db import IntegrityError
from mygpo.log import log
from mygpo.api.sanitizing import sanitize_urls
from django.views.decorators.csrf import csrf_exempt
from mygpo import migrate

LEGACY_DEVICE_NAME = 'Legacy Device'
LEGACY_DEVICE_UID  = 'legacy'

@csrf_exempt
def upload(request):
    try:
        emailaddr = request.POST['username']
        password  = request.POST['password']
        action    = request.POST['action']
        protocol  = request.POST['protocol']
        opml      = request.FILES['opml'].read()
    except MultiValueDictKeyError:
        return HttpResponse("@PROTOERROR", mimetype='text/plain')

    user = auth(emailaddr, password)
    if (not user):
        return HttpResponse('@AUTHFAIL', mimetype='text/plain')

    d = get_device(user, LEGACY_DEVICE_UID)
    dev = migrate.get_or_migrate_device(d)

    existing_urls = [x.url for x in dev.get_subscribed_podcasts()]

    i = Importer(opml)

    podcast_urls = [p['url'] for p in i.items]
    podcast_urls = sanitize_urls(podcast_urls)
    podcast_urls = filter(lambda x: x, podcast_urls)

    new = [u for u in podcast_urls if u not in existing_urls]
    rem = [u for e in existing_urls if u not in podcast_urls]

    #remove duplicates
    new = list(set(new))
    rem = list(set(rem))

    for n in new:
        try:
            p, created = Podcast.objects.get_or_create(url=n)
            p = migrate.get_or_migrate_podcast(p)
        except IntegrityError, e:
            log('/upload: Error trying to get podcast object: %s (error: %s)' % (n, e))
            continue

        try:
            p.subscribe(d)
        except Exception as e:
            log('Legacy API: %(username): could not subscribe to podcast %(podcast_url) on device %(device_id): %(exception)s' %
                {'username': user.username, 'podcast_url': p.url, 'device_id': d.id, 'exception': e})

    for r in rem:
        p, created = Podcast.objects.get_or_create(url=r)
        p = migrate.get_or_migrate_podcast(p)
        try:
            p.unsubscribe(d)
        except Exception as e:
            log('Legacy API: %(username): could not unsubscribe from podcast %(podcast_url) on device %(device_id): %(exception)s' %
                {'username': user.username, 'podcast_url': p.url, 'device_id': d.id, 'exception': e})

    return HttpResponse('@SUCCESS', mimetype='text/plain')

@csrf_exempt
def getlist(request):
    emailaddr = request.GET.get('username', None)
    password = request.GET.get('password', None)

    user = auth(emailaddr, password)
    if user is None:
        return HttpResponse('@AUTHFAIL', mimetype='text/plain')

    d, created = Device.objects.get_or_create(user=user, uid=LEGACY_DEVICE_UID,
        defaults = {'type': 'other', 'name': LEGACY_DEVICE_NAME})

    # We ignore deleted devices, because the Legacy API doesn't know such a concept

    dev = migrate.get_or_migrate_device(d)
    podcasts = dev.get_subscribed_podcasts()

    # FIXME: Get username and set a proper title (e.g. "thp's subscription list")
    title = 'Your subscription list'
    exporter = Exporter(title)

    opml = exporter.generate(podcasts)

    return HttpResponse(opml, mimetype='text/xml')


def auth(emailaddr, password):
    if emailaddr is None or password is None:
        return None

    try:
        user = User.objects.get(email__exact=emailaddr)
    except User.DoesNotExist:
        return None

    if not user.check_password(password):
        return None

    if not user.is_active:
        return None

    return user

