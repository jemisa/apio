# -*- coding: utf-8 -*-
# -- This file is part of the Apio project
# -- (C) 2016-2017 FPGAwars
# -- Author Jesús Arroyo
# -- Licence GPLv2

import re
import click
import shutil
import semantic_version

from os import makedirs, remove, rename
from os.path import isfile, isdir, basename

from apio import util
from apio.api import api_request
from apio.resources import Resources
from apio.profile import Profile

from apio.managers.downloader import FileDownloader
from apio.managers.unpacker import FileUnpacker


class Installer(object):

    def __init__(self, package, platform='', force=False, checkversion=True):

        # Parse version
        if '@' in package:
            split = package.split('@')
            self.package = split[0]
            self.version = split[1]
        else:
            self.package = package
            self.version = None

        self.forced_install = force
        self.packages_dir = ''

        self.resources = Resources(platform)

        if self.package in self.resources.packages:

            self.profile = Profile()

            dirname = 'packages'
            self.packages_dir = util.safe_join(util.get_home_dir(), dirname)

            # Get data
            data = self.resources.packages[self.package]
            distribution = self.resources.distribution

            self.specversion = distribution['packages'][self.package]
            self.package_name = data['release']['package_name']
            self.extension = data['release']['extension']
            platform = platform or self._get_platform()

            if checkversion:
                # Check version
                version = self._get_valid_version(
                    data['repository']['name'],
                    data['repository']['organization'],
                    data['release']['tag_name'],
                    self.version,
                    self.specversion,
                    force
                )

                # Valid version added with @
                if version and self.version:
                    self.forced_install = True
                self.version = version if version else ''

                # Valid version
                if version:
                    # e.g., [linux_x86_64, linux]
                    self.download_urls = [
                        self.get_download_url(data, platform),
                        self.get_download_url(data, platform.split('_')[0])
                    ]

    def get_download_url(self, data, platform):
        compressed_name = data['release']['compressed_name']
        self.compressed_name = compressed_name.replace(
            '%V', self.version).replace('%P', platform)
        uncompressed_name = data['release']['uncompressed_name']
        self.uncompressed_name = uncompressed_name.replace(
            '%V', self.version).replace('%P', platform)

        tarball = self._get_tarball_name(
            self.compressed_name,
            self.extension
        )

        download_url = self._get_download_url(
            data['repository']['name'],
            data['repository']['organization'],
            data['release']['tag_name'].replace(
                '%V', self.version),
            tarball
        )

        return download_url

    def install(self):
        if self.packages_dir == '':
            click.secho(
                'Error: No such package \'{0}\''.format(self.package),
                fg='red')
        elif self.version == '':
            click.secho(
                'Error: No valid version found. Semantic {0}'.format(
                    self.specversion),
                fg='red')
        else:
            click.echo('Installing %s package:' % click.style(
                self.package, fg='cyan'))
            if not isdir(self.packages_dir):
                makedirs(self.packages_dir)
            assert isdir(self.packages_dir)
            dlpath = None
            try:
                # Try full platform
                platform_download_url = self.download_urls[0]
                dlpath = self._download(platform_download_url)
            except Exception as e:
                # Try os name
                os_download_url = self.download_urls[1]
                if platform_download_url != os_download_url:
                    click.secho(
                        'Warnig: full platform do not match. Trying OS name',
                        fg='yellow')
                    try:
                        dlpath = self._download(os_download_url)
                    except Exception as e:
                        click.secho(
                            'Error: package not availabe for this platform',
                            fg='red')
                else:
                    click.secho(
                        'Error: package not availabe for this platform',
                        fg='red')
            if dlpath:
                package_dir = util.safe_join(
                    self.packages_dir, self.package)
                if isdir(package_dir):
                    shutil.rmtree(package_dir)
                if self.uncompressed_name:
                    self._unpack(dlpath, self.packages_dir)
                else:
                    self._unpack(dlpath, util.safe_join(
                        self.packages_dir, self.package_name))
            else:
                if dlpath:
                    remove(dlpath)
                    self.profile.add_package(self.package, self.version)
                    self.profile.save()
                    click.secho(
                        """Package \'{}\' has been """
                        """successfully installed!""".format(self.package),
                        fg='green')

            # Rename unpacked dir to package dir
            if self.uncompressed_name:
                unpack_dir = util.safe_join(
                    self.packages_dir, self.uncompressed_name)
                package_dir = util.safe_join(
                    self.packages_dir, self.package_name)
                if isdir(unpack_dir):
                    rename(unpack_dir, package_dir)

    def uninstall(self):
        if self.packages_dir == '':
            click.secho(
                'Error: No such package \'{0}\''.format(self.package),
                fg='red')
        else:
            if isdir(util.safe_join(self.packages_dir, self.package_name)):
                click.echo('Uninstalling %s package' % click.style(
                    self.package, fg='cyan'))
                shutil.rmtree(
                    util.safe_join(self.packages_dir, self.package_name))
                click.secho(
                    """Package \'{}\' has been """
                    """successfully uninstalled!""".format(self.package),
                    fg='green')
            else:
                click.secho('Package \'{0}\' is not installed'.format(
                    self.package), fg='red')
            self.profile.remove_package(self.package)
            self.profile.save()

    def _get_platform(self):
        return util.get_systype()

    def _get_download_url(self, name, organization, tag, tarball):
        url = 'https://github.com/{0}/{1}/releases/download/{2}/{3}'.format(
            organization,
            name,
            tag,
            tarball)
        return url

    def _get_tarball_name(self, name, extension):
        tarball = '{0}.{1}'.format(
            name,
            extension)
        return tarball

    def _get_valid_version(self, name, organization, tag_name,
                           version='', specversion='', force=False):
        # Check spec version
        try:
            spec = semantic_version.Spec(specversion)
        except ValueError:
            click.secho('Invalid distribution version {0}: {1}'.format(
                        name, specversion), fg='red')
            exit(1)

        # Download latest releases list
        releases = api_request('{}/releases'.format(name), organization)
        if releases is not None:
            for release in releases:
                if 'tag_name' in release and (not release['prerelease'] or force):
                    if version:
                        # Version number via @
                        tag = tag_name.replace('%V', version)
                        if tag == release['tag_name']:
                            return self._check_sem_version(version, spec)
                    else:
                        pattern = tag_name.replace('%V', '(?P<v>.*?)') + '$'
                        match = re.search(pattern, release['tag_name'])
                        if match:
                            version = match.group('v')
                            return self._check_sem_version(version, spec)

    def _check_sem_version(self, version, spec):
        try:
            if semantic_version.Version(version) in spec:
                return version
        except ValueError:
            if version in str(spec):
                return version

    def _download(self, url):
        # Note: here we check only for the version of locally installed
        # packages. For this reason we don't say what's the installation
        # path.
        if self.profile.check_package_version(self.package, self.version) \
           or self.forced_install:
            fd = FileDownloader(url, self.packages_dir)
            filepath = fd.get_filepath()
            click.secho('Download ' + basename(filepath))
            try:
                fd.start()
            except KeyboardInterrupt:
                if isfile(filepath):
                    remove(filepath)
                click.secho('Abort download!', fg='red')
                exit(1)
            return filepath
        else:
            click.secho('Already installed. Version {0}'.format(
                self.profile.get_package_version(self.package)), fg='yellow')
            return None

    def _unpack(self, pkgpath, pkgdir):
        fu = FileUnpacker(pkgpath, pkgdir)
        return fu.start()
