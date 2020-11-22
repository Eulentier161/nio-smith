"""
    Imports all plugins from plugins subdirectory

"""

from plugin import Plugin, PluginCommand, PluginHook

from sys import modules
from re import match
from time import time
import operator
from typing import List, Dict, Callable

import logging
logger = logging.getLogger(__name__)

from fuzzywuzzy import fuzz
# from pprint import pprint


# import all plugins
try:
    from plugins import *
except ImportError as err:
    logger.critical(f"Error importing plugin: {err.name}: {err}")
except KeyError as err:
    logger.critical(f"Error importing plugin: {err}")


class PluginLoader:

    def __init__(self):
        # get all loaded plugins from sys.modules and make them available as plugin_list
        self.__plugin_list: Dict[str, Plugin] = {}
        self.commands: Dict[str, PluginCommand] = {}
        self.help_texts: Dict[str, str] = {}
        self.hooks: Dict[str, List[PluginHook]] = {}
        self.timers: List[Callable] = []

        for key in modules.keys():
            if match("^plugins\.\w*", key):
                # TODO: this needs to catch exceptions
                found_plugin: Plugin = modules[key].plugin
                if isinstance(found_plugin, Plugin):
                    self.__plugin_list[found_plugin.name] = found_plugin

        for plugin in self.__plugin_list.values():

            """assemble all valid commands and their respective methods"""
            self.commands.update(plugin.get_commands())

            """assemble all hooks and their respective methods"""
            event_type: str
            plugin_hooks: List[PluginHook]
            plugin_hook: PluginHook
            for event_type, plugin_hooks in plugin.get_hooks().items():
                if event_type in self.hooks.keys():
                    for plugin_hook in plugin_hooks:
                        self.hooks[event_type].append(plugin_hook)
                else:
                    self.hooks[event_type] = plugin_hooks

            """assemble all timers and their respective methods"""
            self.timers.extend(plugin.get_timers())

            """load the plugin's saved data"""
            plugin.plugin_data = plugin.load_data()
            logger.info(f"Loaded plugin {plugin.name}:")
            if plugin.get_commands() != {}:
                logger.info(f"  Commands: {', '.join([*plugin.get_commands().keys()])}")
            if plugin.get_hooks() != {}:
                logger.info(f"  Hooks:    {', '.join([*plugin.get_hooks().keys()])}")
            if plugin.get_timers():
                timers: List[str] = []
                for timer in plugin.get_timers():
                    timers.append(timer.__name__)
                logger.info(f"  Timers:   {', '.join(timers)}")

    def get_plugins(self) -> Dict[str, Plugin]:

        return self.__plugin_list

    def get_plugin_by_name(self, name: str) -> Plugin or None:

        """Try to find a plugin by the name provided and return it"""

        try:
            return self.get_plugins()[name]
        except KeyError:
            return None

    def get_hooks(self) -> Dict[str, List[PluginHook]]:

        return self.hooks

    def get_commands(self) -> Dict[str, PluginCommand]:

        return self.commands

    def get_timers(self) -> List[Callable]:

        return self.timers

    async def run_command(self, command) -> int:
        """

        :param command:
        :return:    0 if command was found and executed successfully
                    1 if command was not found (or not valid for room)
                    2 if command was found, but required power_level was not met
        """

        logger.debug(f"Running Command {command.command} with args {command.args}")

        command_start = command.command.split()[0].lower()
        run_command: str = ""

        if command_start in self.commands.keys():
            run_command = command_start

        # Command not found, try fuzzy matching
        else:
            ratios: Dict[str, int] = {}
            for key in self.commands.keys():
                if fuzz.ratio(command_start, key) > 60:
                    ratios[key] = fuzz.ratio(command_start, key)

            # Sort matching commands by match percentage and get the highest match
            if ratios != {}:
                run_command = sorted(ratios.items(), key=operator.itemgetter(1), reverse=True)[0][0]

        # check if we did actually find a matching command
        if run_command != "":
            if self.commands[run_command].room_id is None or command.room.room_id in self.commands[run_command].room_id:

                # check if the user's power_level matches the command's requirement
                if command.room.power_levels.get_user_level(command.event.sender) >= self.commands[run_command].power_level:

                    # Make sure, exceptions raised by plugins do not kill the bot
                    try:
                        await self.commands[run_command].method(command)
                    except Exception as err:
                        logger.critical(f"Plugin failed to catch exception caused by {command_start}: {err}")
                    return 0
                else:
                    return 2
            else:
                return 1

    async def run_hooks(self, client, event_type: str, room, event):

        if event_type in self.hooks.keys():
            event_hooks: List[PluginHook] = self.hooks[event_type]

            event_hook: PluginHook
            for event_hook in event_hooks:
                if event_hook.room_id is None or room.room_id in event_hook.room_id:
                    # Make sure, exceptions raised by plugins do not kill the bot
                    try:
                        await event_hook.method(client, room.room_id, event)
                    except Exception as err:
                        logger.critical(f"Plugin failed to catch exception caused by hook {event_hook.method} on"
                                        f" {room} for {event}: {err}")

    async def run_timers(self, client, timestamp: float) -> float:

        """Do not run timers more often than every 30s"""
        if time() >= timestamp+30:
            for timer in self.get_timers():
                try:
                    await timer(client)
                except Exception as err:
                    logger.critical(f"Plugin failed to catch exception in {timer}: {err}")
            return time()
        else:
            return timestamp
