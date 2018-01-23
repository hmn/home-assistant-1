"""Playstation 4 media_player using ps4-waker."""
import json
# import re
import logging
from datetime import timedelta

import voluptuous as vol

import homeassistant.util as util
from homeassistant.components.media_player import (
    PLATFORM_SCHEMA,
    MEDIA_TYPE_CHANNEL,
    SUPPORT_TURN_ON,
    SUPPORT_TURN_OFF,
    SUPPORT_STOP,
    SUPPORT_SELECT_SOURCE,
    ENTITY_IMAGE_URL,
    MediaPlayerDevice
)
from homeassistant.const import (
    STATE_IDLE,
    STATE_UNKNOWN,
    STATE_OFF,
    STATE_PLAYING,
    CONF_NAME,
    CONF_HOST,
    CONF_FILENAME
)
from homeassistant.helpers import config_validation as cv
from homeassistant.util.json import load_json, save_json

REQUIREMENTS = [
    'https://github.com/hthiery/python-ps4/archive/master.zip'
    '#pyps4==dev']

_CONFIGURING = {}
_LOGGER = logging.getLogger(__name__)

SUPPORT_PS4 = SUPPORT_TURN_OFF | SUPPORT_TURN_ON | \
    SUPPORT_STOP | SUPPORT_SELECT_SOURCE

DEFAULT_NAME = 'Playstation 4'
ICON = 'mdi:playstation'
CONF_CREDENTIALS_FILENAME = "credentials_filename"
CONF_GAMES_FILENAME = 'games_filename'
CONF_LOCAL_STORE = "local_store"

CREDENTIALS_FILE = None
PS4_GAMES_FILE = 'ps4-games.json'
MEDIA_IMAGE_DEFAULT = None
LOCAL_STORE = 'games'
CONFIG_FILE = 'ps4.conf'

MIN_TIME_BETWEEN_SCANS = timedelta(seconds=10)
MIN_TIME_BETWEEN_FORCED_SCANS = timedelta(seconds=1)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_FILENAME, default=CONFIG_FILE): cv.string,
    vol.Optional(CONF_CREDENTIALS_FILENAME,
                 default=CREDENTIALS_FILE): cv.string,
    vol.Optional(CONF_GAMES_FILENAME, default=PS4_GAMES_FILE): cv.string,
    vol.Optional(CONF_LOCAL_STORE, default=LOCAL_STORE): cv.string
})


def _check_ps4(host, credentials):
    """Check if PS4 is responding."""
    import pyps4

    if host is None:
        return False

    if credentials is None:
        return False

    try:
        try:
            playstation = pyps4.Ps4(host, credentials)
            info = playstation.get_status()
            _LOGGER.debug("Searched for PS4 [%s] on network and got : %s",
                          host, info)
        except IOError as e:
            _LOGGER.error("Error connecting to PS4 [%s] : %s", host, e)
            return False
        finally:
            playstation.close()

    except (IOError, OSError) as e:
        _LOGGER.error("Error loading PS4 [%s] credentials : %s", host, e)
        return False

    return True


def setup_ps4(host, name, hass, config, add_devices, credentials):
    """Set up PS4."""
    games_filename = hass.config.path(config.get(CONF_GAMES_FILENAME))
    local_store = config.get(CONF_LOCAL_STORE)

    ps4 = PS4(host, credentials, games_filename)
    add_devices([PS4Device(name, ps4, local_store)], True)


def request_configuration(host, name, hass, config, add_devices, credentials):
    """Request configuration steps from the user."""
    configurator = hass.components.configurator
    # We got an error if this method is called while we are configuring
    if host in _CONFIGURING:
        configurator.notify_errors(
            _CONFIGURING[host],
            'Failed to register host, please try again [%s].',
            host)

        return

    def ps4_configuration_callback(data):
        """Handle configuration changes."""
        credentials = data.get('credentials')
        if _check_ps4(host, credentials):
            setup_ps4(host, name, hass,
                      config, add_devices, credentials)

            def success():
                """Set up was successful."""
                conf = load_json(hass.config.path(config.get(CONF_FILENAME)))
                conf[host] = {'credentials': credentials}
                save_json(hass.config.path(config.get(CONF_FILENAME)), conf)
                req_config = _CONFIGURING.pop(host)
                hass.async_add_job(configurator.request_done, req_config)

            hass.async_add_job(success)

    _CONFIGURING[host] = configurator.request_config(
        DEFAULT_NAME,
        ps4_configuration_callback,
        description='Enter credentials',
        # entity_picture='/static/images/logo_ps4.png',
        link_name='Howto generate credentials',
        link_url='https://home-assistant.io/components/media_player.ps4/',
        submit_caption='Confirm',
        fields=[{
            'id': 'credentials',
            'name': 'PS4-Waker credentials json',
            'type': 'text'
        }])


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the PS4 platform."""
    if discovery_info is not None:
        host = discovery_info.get(CONF_HOST)
        name = DEFAULT_NAME
        credentials = None
    else:
        host = config.get(CONF_HOST)
        name = config.get(CONF_NAME, DEFAULT_NAME)
        if config.get(CONF_CREDENTIALS_FILENAME) is not None:
            credentials = hass.config.path(
                config.get(CONF_CREDENTIALS_FILENAME))
        else:
            credentials = None

    if not credentials:
        conf = load_json(hass.config.path(config.get(CONF_FILENAME)))
        if conf.get(host, {}).get('credentials'):
            credentials = conf[host]['credentials']

    if not _check_ps4(host, credentials):
        request_configuration(host, name, hass, config,
                              add_devices, credentials)
        return

    setup_ps4(host, name, hass,
              config, add_devices, credentials)


class PS4Device(MediaPlayerDevice):
    """Representation of a PS4."""

    def __init__(self, name, ps4, local_store):
        """Initialize the ps4 device."""
        self.ps4 = ps4
        self._name = name
        self._state = STATE_UNKNOWN
        self._media_content_id = None
        self._media_title = None
        self._current_source = None
        self._current_source_id = None
        self._gamesmap = {}
        self._local_store = local_store
        self.update()

    @util.Throttle(MIN_TIME_BETWEEN_SCANS, MIN_TIME_BETWEEN_FORCED_SCANS)
    def update(self):
        """Retrieve the latest data."""
        data = self.ps4.get_status()
        _LOGGER.debug("ps4 get_status, %s" % data)

        self._media_title = data.get('running-app-name')
        self._media_content_id = data.get('running-app-titleid')
        self._current_source = data.get('running-app-name')
        self._current_source_id = data.get('running-app-titleid')

        if data.get('status') == 'Ok':
            if self._media_content_id is not None:
                self._state = STATE_PLAYING
                # Check if cover art is in the gamesmap
                self.check_gamesmap()
            else:
                self._state = STATE_IDLE
        else:
            self._state = STATE_OFF
            self._media_title = None
            self._media_content_id = None
            self._current_source = None
            self._current_source_id = None

    def check_gamesmap(self):
        """Check games map for coverart."""
        if self._media_content_id not in self._gamesmap:
            # Attempt to get cover art from playstation store
            self.ps_store_cover_art()

    def ps_store_cover_art(self):
        """Store coverart from PS store in games map."""
        import requests
        import urllib

        cover_art = None
        try:
            url = 'https://store.playstation.com'
            url += '/valkyrie-api/en/US/19/faceted-search/'
            url += urllib.parse.quote(self._media_title.encode('utf-8'))
            url += '?query='
            url += urllib.parse.quote(self._media_title.encode('utf-8'))
            url += '&platform=ps4'
            headers = {
                'User-Agent':
                    'Mozilla/5.0 '
                    '(Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36'
            }
            r = requests.get(url, headers=headers)

            for item in r.json()['included']:
                if 'attributes' in item:
                    game = item['attributes']
                    if 'game-content-type' in game and \
                       ('App' or 'Game') in game['game-content-type']:
                        if 'thumbnail-url-base' in game:
                            cover_art = game['thumbnail-url-base']
                            cover_art += '?w=512&h=512'
                            print("image, %s" % cover_art)
                            break
        except requests.exceptions.HTTPError as e:
            _LOGGER.error("PS cover art HTTP error, %s" % e)

        except requests.exceptions.RequestException as e:
            _LOGGER.error("PS cover art request failed, %s" % e)

        if cover_art is not None:
            self._gamesmap[self._media_content_id] = cover_art

    @property
    def entity_picture(self):
        """Return picture."""
        if self.state == STATE_OFF:
            return None

        image_hash = self.media_image_hash
        if image_hash is not None:
            return ENTITY_IMAGE_URL.format(
                self.entity_id, self.access_token, image_hash)

        if self._media_content_id is None:
            return None

        filename = "/local/%s/%s.jpg" % \
            (self._local_store, self._media_content_id)
        return filename

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def icon(self):
        """Icon."""
        return ICON

    @property
    def media_content_id(self):
        """Content ID of current playing media."""
        return self._media_content_id

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        return MEDIA_TYPE_CHANNEL

    @property
    def media_image_url(self):
        """Image url of current playing media."""
        if self._media_content_id is None:
            return MEDIA_IMAGE_DEFAULT
        try:
            return self._gamesmap[self._media_content_id]
        except KeyError:
            return MEDIA_IMAGE_DEFAULT

    @property
    def media_title(self):
        """Title of current playing media."""
        return self._media_title

    @property
    def supported_features(self):
        """Media player features that are supported."""
        return SUPPORT_PS4

    @property
    def source(self):
        """Return the current input source."""
        return self._current_source

    @property
    def source_list(self):
        """List of available input sources."""
        return sorted(self.ps4.games.values())

    def turn_off(self):
        """Turn off media player."""
        # self.ps4.ps.standby()
        _LOGGER.error('PS4 standby not implemented')

    def turn_on(self):
        """Turn on the media player."""
        self.ps4.wakeup()
        self.update()

    def media_pause(self):
        """Send keypress ps to return to menu."""
        self.ps4.remote('ps')
        self.update()

    def media_stop(self):
        """Send keypress ps to return to menu."""
        self.ps4.remote('ps')
        self.update()

    def select_source(self, source):
        """Select input source."""
        for titleid, game in self.ps4.games.items():
            if source == game:
                self.ps4.start(titleid)
                self._current_source_id = titleid
                self._current_source = game
                self._media_content_id = titleid
                self._media_title = game
                self.update()


class PS4(object):
    """The class for handling the data retrieval."""

    def __init__(self, host, credentials, games_filename):
        """Initialize the data object."""
        import pyps4

        self._host = host
        self._credentials = credentials
        self._games_filename = games_filename
        self.games = {}
        self._load_games()

        try:
            self.ps = pyps4.Ps4(self._host, self._credentials)
            self.ps.open()

        except (IOError, OSError) as e:
            _LOGGER.error("Error loading PS4 credentials [%s] : %s",
                          self._host, e)
            return False

    def _load_games(self):
        _LOGGER.debug('_load_games: %s', self._games_filename)
        try:
            with open(self._games_filename, 'r') as f:
                self.games = json.load(f)
                f.close()
        except FileNotFoundError:
            self._save_games()
        except ValueError as e:
            _LOGGER.error('Games json file wrong: %s', e)

    def _save_games(self):
        _LOGGER.debug('_save_games: %s', self._games_filename)
        try:
            with open(self._games_filename, 'w') as f:
                json.dump(self.games, f)
                f.close()
        except FileNotFoundError:
            pass

    def get_status(self):
        """List current info."""
        data = self.ps.get_status()

        if data is None:
            return {}

        """Save current game"""
        if data.get('running-app-titleid'):
            if data.get('running-app-titleid') not in self.games.keys():
                game = {data.get('running-app-titleid'):
                        data.get('running-app-name')}
                self.games.update(game)
                self._save_games()

        # return data
        return data

    def wakeup(self):
        """Wakeup PS4."""
        return self.ps.wakeup()

    def start(self, titleId):
        """Start game using titleId."""
        _LOGGER.warning('PS4 command not implemented : start %s', titleId)
        return None
        # return self._run('start ' + titleId)

    def remote(self, key):
        """Send remote key press."""
        _LOGGER.warning('PS4 command not implemented : remote %s', key)
        return None
        # return self._run('remote ' + key)
