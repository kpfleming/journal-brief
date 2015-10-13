"""
Copyright (c) 2015 Tim Waugh <tim@cyberelk.net>

## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.

## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.

## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
"""

import argparse
import logging
import os
import sys

from journal_brief import (SelectiveReader,
                           LatestJournalEntries,
                           get_formatter,
                           list_formatters,
                           JournalFilter)
from journal_brief.config import Config, ConfigError
from journal_brief.constants import PACKAGE, CONFIG_DIR, PRIORITY_MAP
from journal_brief.debrief import Debriefer


log = logging.getLogger('cli')


class InstanceConfig(object):
    def __init__(self, config, args):
        self.config = config
        self.args = args

    def get(self, key, default_value=None):
        config_key = key.replace('_', '-')
        args_key = key.replace('-', '_')
        try:
            value = getattr(self.args, args_key)
            log.debug("%s=%r from args", args_key, value)
        except AttributeError:
            value = None
        finally:
            if value is None:
                value = self.config.get(config_key, default_value)
                if value is not None:
                    log.debug("%s=%r from config", args_key, value)

        return value


class NullStream(object):
    def write(self, data):
        pass


class CLI(object):
    def __init__(self, args=None):
        self.args = self.get_args(args or sys.argv[1:])
        config = Config(config_file=self.args.conf)
        self.config = InstanceConfig(config, self.args)

    @staticmethod
    def get_args(args):
        description = 'Show new journal entries since last run'
        parser = argparse.ArgumentParser(description=description)
        parser.add_argument('-b', action='store_true', default=False,
                            help='process all entries from the current boot')
        parser.add_argument('-p', '--priority', metavar='PRI',
                            help='show entries at priority PRI and lower',
                            choices=['emerg', 'alert', 'crit', 'err',
                                     'warning', 'notice', 'info', 'debug'])
        parser.add_argument('--conf', metavar='FILE',
                            help='use FILE as config file')
        parser.add_argument('--debug', action='store_true', default=False,
                            help='enable debugging')
        parser.add_argument('--dry-run', action='store_true', default=False,
                            help='do not update cursor bookmark file')
        helptxt = ('output format for journal entries, '
                   'comma-separated list from {0}'.format(list_formatters()))
        parser.add_argument('-o', '--output', metavar='FORMAT', help=helptxt)
        parser.add_argument('--help-output', action='store_true',
                            default=False,
                            help='display information about output formats')

        cmds = parser.add_subparsers(dest='cmd')
        cmds.add_parser('debrief', help='create exclusions config')
        cmds.add_parser('reset', help='reset cursor bookmark and exit')
        cmds.add_parser('stats', help='show statistics')
        return parser.parse_args(args)

    def show_stats(self, jfilter):
        jfilter.format(NullStream())
        stats = jfilter.get_statistics()
        log.debug("stats: %r", stats)
        strf = "{FREQ:>10}  {EXCLUSION}"
        print(strf.format(FREQ='FREQUENCY', EXCLUSION='EXCLUSION'))
        for stat in stats:
            print(strf.format(FREQ=stat.hits,
                              EXCLUSION=repr(dict(stat.exclusion))))

    def run(self):
        default_output_format = 'reboot,short'

        if self.args.help_output:
            print("Available output formats:")
            for output in list_formatters():
                print("\n{0}:".format(output))
                formatter = get_formatter(output)
                docstring = [line.strip()
                             for line in formatter.__doc__.splitlines()]
                while docstring and not docstring[0]:
                    del docstring[0]
                while docstring and not docstring[-1]:
                    del docstring[-1]
                print('\n'.join(['    ' + line for line in docstring]))

            print("\nMultiple output formats can be used at the same time.")
            print("The default is '{0}'".format(default_output_format))
            return

        if self.config.get('debug'):
            logging.basicConfig(level=logging.DEBUG)

        cursor_file = self.config.get('cursor-file')
        if not cursor_file.startswith('/'):
            cursor_file = os.path.join(CONFIG_DIR, cursor_file)

        log.debug("cursor-file=%r", cursor_file)
        if self.args.cmd == 'reset':
            log.debug('reset: removing %r', cursor_file)
            try:
                os.unlink(cursor_file)
            except IOError:
                pass

            return

        log_level = None
        priority = self.config.get('priority')
        if priority:
            log_level = int(PRIORITY_MAP[priority])
            log.debug("priority=%r from args/config", log_level)

        if self.args.cmd == 'debrief':
            formatters = [get_formatter('config')]
        else:
            outputs = self.config.get('output',
                                      default_output_format).split(',')
            formatters = [get_formatter(output) for output in outputs]

        if any(formatter.FILTER_INCLUSIONS is None
               for formatter in formatters):
            default_inclusions = self.config.get('inclusions')
        else:
            # None of our formatters need the inclusions from config
            default_inclusions = None

        if default_inclusions:
            inclusions = default_inclusions[:]
        else:
            inclusions = []

        for formatter in formatters:
            if formatter.FILTER_INCLUSIONS is not None:
                inclusions.extend(formatter.FILTER_INCLUSIONS)

        reader = SelectiveReader(this_boot=self.args.b,
                                 log_level=log_level,
                                 inclusions=inclusions)
        with LatestJournalEntries(cursor_file=cursor_file,
                                  reader=reader,
                                  dry_run=self.args.dry_run,
                                  seek_cursor=not self.args.b) as entries:
            exclusions = self.config.get('exclusions', [])
            jfilter = JournalFilter(entries, formatters,
                                    default_inclusions=default_inclusions,
                                    default_exclusions=exclusions)
            if self.args.cmd == 'stats':
                self.show_stats(jfilter)
            else:
                jfilter.format(sys.stdout)


def run():
    try:
        CLI().run()
    except KeyboardInterrupt:
        pass
    except IOError as ex:
        sys.stderr.write("{0}: {1}\n".format(PACKAGE, os.strerror(ex.errno)))
        sys.exit(1)
    except ConfigError:
        sys.exit(1)


if __name__ == '__main__':
    run()
