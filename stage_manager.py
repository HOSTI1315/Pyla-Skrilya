import os.path
import sys

import asyncio
import time

import cv2
import numpy as np

from state_finder import get_state, find_game_result, get_star_drop_type, is_in_prestige_reward
from trophy_observer import TrophyObserver
from utils import find_template_center, load_toml_as_dict, async_notify_user, \
    save_brawler_data
from adaptive_brain import AdaptiveBrain

debug = load_toml_as_dict("cfg/general_config.toml")['super_debug'] == "yes"


def load_image(image_path, scale_factor):
    # Load the image
    image = cv2.imread(image_path)
    orig_height, orig_width = image.shape[:2]

    # Calculate the new dimensions based on the scale factor
    new_width = int(orig_width * scale_factor)
    new_height = int(orig_height * scale_factor)

    # Resize the image
    resized_image = cv2.resize(image, (new_width, new_height))
    return resized_image

class StageManager:

    def __init__(self, brawlers_data, lobby_automator, window_controller):
        self.Lobby_automation = lobby_automator
        self.lobby_config = load_toml_as_dict("./cfg/lobby_config.toml")
        self.close_popup_icon = None
        self.brawlers_pick_data = brawlers_data
        self.started_trophies_by_brawler = {}
        for brawler in brawlers_data:
            name = str(brawler.get("brawler", "")).lower()
            if name:
                self.started_trophies_by_brawler[name] = brawler.get("trophies", 0)
        brawler_list = [brawler["brawler"] for brawler in brawlers_data]
        self.Trophy_observer = TrophyObserver(brawler_list)
        bot_config = load_toml_as_dict("cfg/bot_config.toml")
        adaptive_enabled = str(bot_config.get("adaptive_brain_enabled", "yes")).lower() in ("yes", "true", "1")
        adaptive_window = int(bot_config.get("adaptive_brain_window", 20))
        self.adaptive_brain = AdaptiveBrain(enabled=adaptive_enabled, window_size=adaptive_window)
        print(self.adaptive_brain.summary())
        self.time_since_last_stat_change = time.time()
        # Guards against recording trophies twice when end_game() is re-entered
        # on the same end-of-match screen (e.g. because the dismiss button
        # didn't clear the screen before the outer loop called us again).
        self.last_recorded_result_time = 0.0
        self.last_recorded_result = None
        self.active_end_result = None
        self.long_press_star_drop = load_toml_as_dict("./cfg/general_config.toml")["long_press_star_drop"]
        time_thresholds = load_toml_as_dict("./cfg/time_tresholds.toml")
        self.end_screen_dismiss_delay = float(time_thresholds.get("end_screen_dismiss_delay", 0.35))
        self.window_controller = window_controller
        self.states = {
            'shop': self.quit_shop,
            'brawler_selection': self.quit_shop,
            'popup': self.close_pop_up,
            'match': lambda: 0,
            'end_draw': self.end_game,
            'end_victory': self.end_game,
            'end_defeat': self.end_game,
            # Showdown trio: finishing places 1-4
            'end_1st': self.end_game,
            'end_2nd': self.end_game,
            'end_3rd': self.end_game,
            'end_4th': self.end_game,
            'lobby': self.start_game,
            'star_drop': self.click_star_drop,
            'prestige_reward': self.handle_prestige_reward,
            'trophy_reward': lambda: self.window_controller.press_key("Q")
        }

    def send_webhook_notification(self, event_type, screenshot=None, details=None):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(async_notify_user(event_type, screenshot, details=details or {}))
        finally:
            loop.close()

    def current_target_details(self, extra=None):
        current = self.brawlers_pick_data[0] if self.brawlers_pick_data else {}
        type_to_push = current.get("type", "trophies")
        values = {
            "trophies": self.Trophy_observer.current_trophies,
            "wins": self.Trophy_observer.current_wins,
        }
        details = {
            "brawler": current.get("brawler", ""),
            "started_trophies": self.started_trophies_by_brawler.get(
                str(current.get("brawler", "")).lower(),
                current.get("trophies", 0),
            ),
            "trophies": values.get(type_to_push, self.Trophy_observer.current_trophies),
            "target": current.get("push_until", ""),
            "wins": self.Trophy_observer.current_wins,
            "win_streak": self.Trophy_observer.win_streak,
            "brawlers_left": len(self.brawlers_pick_data),
        }
        if extra:
            details.update(extra)
        return details

    @staticmethod
    def validate_trophies(trophies_string):
        trophies_string = trophies_string.lower()
        while "s" in trophies_string:
            trophies_string = trophies_string.replace("s", "5")
        numbers = ''.join(filter(str.isdigit, trophies_string))

        if not numbers:
            return False

        trophy_value = int(numbers)
        return trophy_value

    def start_game(self):
        print("state is lobby, starting game")
        values = {
            "trophies": self.Trophy_observer.current_trophies,
            "wins": self.Trophy_observer.current_wins
        }

        type_of_push = self.brawlers_pick_data[0]['type']
        if type_of_push not in values:
            type_of_push = "trophies"
        value = values[type_of_push]
        if value == "" and type_of_push == "wins":
            value = 0
        push_current_brawler_till = self.brawlers_pick_data[0]['push_until']
        if push_current_brawler_till == "" and type_of_push == "wins":
            push_current_brawler_till = 300
        if push_current_brawler_till == "" and type_of_push == "trophies":
            push_current_brawler_till = 1000

        if value >= push_current_brawler_till:
            if len(self.brawlers_pick_data) <= 1:
                print("Brawler reached required trophies/wins. No more brawlers selected for pushing in the menu. "
                      "Bot will now pause itself until closed.", value, push_current_brawler_till)
                screenshot = self.window_controller.screenshot()
                self.send_webhook_notification(
                    "completed",
                    screenshot,
                    self.current_target_details({"target": push_current_brawler_till}),
                )
                print("Bot stopping: all targets completed with no more brawlers.")
                self.window_controller.keys_up(list("wasd"))
                self.window_controller.close()
                sys.exit(0)
            completed_brawler = self.brawlers_pick_data[0]["brawler"]
            screenshot = self.window_controller.screenshot()
            self.send_webhook_notification(
                "brawler_complete",
                screenshot,
                self.current_target_details({
                    "brawler": completed_brawler,
                    "target": push_current_brawler_till,
                    "brawlers_left": max(0, len(self.brawlers_pick_data) - 1),
                }),
            )
            self.brawlers_pick_data.pop(0)
            self.Trophy_observer.change_trophies(self.brawlers_pick_data[0]['trophies'])
            self.Trophy_observer.current_wins = self.brawlers_pick_data[0]['wins'] if self.brawlers_pick_data[0]['wins'] != "" else 0
            self.Trophy_observer.win_streak = self.brawlers_pick_data[0]['win_streak']
            next_brawler_name = self.brawlers_pick_data[0]['brawler']
            if self.brawlers_pick_data[0]["automatically_pick"]:
                selection_method = self.brawlers_pick_data[0].get("selection_method", "named_brawler")
                print("Picking next automatically picked brawler")
                screenshot = self.window_controller.screenshot()
                current_state = get_state(screenshot)
                if current_state != "lobby":
                    print("Trying to reach the lobby to switch brawler")

                max_attempts = 30
                attempts = 0
                while current_state != "lobby" and attempts < max_attempts:
                    self.window_controller.press_key("Q")
                    print("Pressed Q to return to lobby")
                    time.sleep(1)
                    screenshot = self.window_controller.screenshot()
                    current_state = get_state(screenshot)
                    attempts += 1
                if attempts >= max_attempts:
                    print("Failed to reach lobby after max attempts")
                else:
                    if selection_method == "lowest_trophies":
                        self.Lobby_automation.select_lowest_trophy_brawler()
                    else:
                        self.Lobby_automation.select_brawler(next_brawler_name)
            else:
                print("Next brawler is in manual mode, waiting 10 seconds to let user switch.")

        # q btn is over the start btn
        self.window_controller.keys_up(list("wasd"))
        self.window_controller.press_key("Q")
        print("Pressed Q to start a match")
    def click_star_drop(self):
        screenshot = self.window_controller.screenshot()
        star_drop_type = get_star_drop_type(cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR))
        if star_drop_type in ("angelic", "demonic"):
            print(f"{star_drop_type.capitalize()} star drop detected; forcing long press.")
            self.window_controller.press_key("Q", 10)
            return

        if star_drop_type == "standard":
            print("Standard star drop detected; fast tapping.")
            for _ in range(5):
                self.window_controller.press_key("Q")
                time.sleep(0.08)
            return

        if self.long_press_star_drop == "yes":
            self.window_controller.press_key("Q", 10)
        else:
            self.window_controller.press_key("Q")

    def advance_to_next_brawler_after_prestige(self):
        if not self.brawlers_pick_data:
            return False
        current_brawler = self.brawlers_pick_data[0].get("brawler", "current")
        print(f"Prestige reward detected for {current_brawler}; treating current brawler as completed.")
        self.brawlers_pick_data[0]["trophies"] = max(1000, int(self.brawlers_pick_data[0].get("trophies") or 0))
        self.brawlers_pick_data[0]["push_until"] = max(1000, int(self.brawlers_pick_data[0].get("push_until") or 1000))

        if len(self.brawlers_pick_data) <= 1:
            print("Prestige reward reached, but no next brawler is queued.")
            save_brawler_data(self.brawlers_pick_data)
            return False

        self.brawlers_pick_data.pop(0)
        next_data = self.brawlers_pick_data[0]
        self.Trophy_observer.change_trophies(next_data.get("trophies", 0))
        self.Trophy_observer.current_wins = next_data.get("wins", 0) if next_data.get("wins", "") != "" else 0
        self.Trophy_observer.win_streak = next_data.get("win_streak", 0)
        save_brawler_data(self.brawlers_pick_data)
        return True

    def handle_prestige_reward(self):
        screenshot = self.window_controller.screenshot()
        if not is_in_prestige_reward(cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)):
            print("Prestige reward state ignored; NEXT button was not confirmed.")
            return

        print("Prestige reward screen detected; clicking NEXT.")
        self.window_controller.keys_up(list("wasd"))
        self.window_controller.click(
            int(1410 * self.window_controller.width_ratio),
            int(990 * self.window_controller.height_ratio),
        )
        time.sleep(1.0)

        if not self.advance_to_next_brawler_after_prestige():
            self.window_controller.press_key("Q")
            return

        current_state = get_state(self.window_controller.screenshot())
        attempts = 0
        while current_state != "lobby" and attempts < 30:
            self.window_controller.press_key("Q")
            time.sleep(1.0)
            current_state = get_state(self.window_controller.screenshot())
            attempts += 1

        if current_state != "lobby":
            print("Could not reach lobby after prestige reward; will retry from normal state loop.")
            return

        self.Lobby_automation.select_lowest_trophy_brawler()

    def end_game(self):
        screenshot = self.window_controller.screenshot()

        found_game_result = False
        current_state = get_state(screenshot)
        button_pressed = False
        end_screen_time = time.time()

        # If this is a re-entry on the same lingering end-of-match screen,
        # skip recording and just keep trying to dismiss it.
        current_result = current_state.split("_", 1)[1] if current_state.startswith("end_") else None
        already_recorded = current_result is not None and self.active_end_result == current_result
        stats_recorded = already_recorded
        if already_recorded:
            found_game_result = current_result
            print(f"end_game: re-entry on '{current_state}', skipping trophy update")

        while current_state.startswith("end") and time.time() - end_screen_time < 25:
            if not stats_recorded:
                found_game_result = current_state.split("_")[1]
                current_brawler = self.brawlers_pick_data[0]['brawler']
                self.Trophy_observer.add_trophies(found_game_result, current_brawler)
                self.Trophy_observer.add_win(found_game_result)
                self.adaptive_brain.record_result(found_game_result)
                self.time_since_last_stat_change = time.time()
                self.last_recorded_result = found_game_result
                self.last_recorded_result_time = time.time()
                self.active_end_result = found_game_result
                stats_recorded = True
                values = {
                    "trophies": self.Trophy_observer.current_trophies,
                    "wins": self.Trophy_observer.current_wins
                }
                type_to_push = self.brawlers_pick_data[0]['type']
                if type_to_push not in values:
                    type_to_push = "trophies"
                value = values[type_to_push]
                self.brawlers_pick_data[0][type_to_push] = value
                self.brawlers_pick_data[0]['win_streak'] = self.Trophy_observer.win_streak
                save_brawler_data(self.brawlers_pick_data)
                self.send_webhook_notification(
                    "match",
                    screenshot,
                    self.current_target_details({
                        "result": found_game_result,
                        "target": self.brawlers_pick_data[0].get("push_until", ""),
                    }),
                )
                push_current_brawler_till = self.brawlers_pick_data[0]['push_until']

                if value == "" and type_to_push == "wins":
                    value = 0
                if push_current_brawler_till == "" and type_to_push == "wins":
                    push_current_brawler_till = 300
                if push_current_brawler_till == "" and type_to_push == "trophies":
                    push_current_brawler_till = 1000

                if value >= push_current_brawler_till:
                    if len(self.brawlers_pick_data) <= 1:
                        print(
                            "Brawler reached required trophies/wins. No more brawlers selected for pushing in the menu. "
                            "Bot will now pause itself until closed.")
                        screenshot = self.window_controller.screenshot()
                        self.send_webhook_notification(
                            "completed",
                            screenshot,
                            self.current_target_details({
                                "result": found_game_result,
                                "target": push_current_brawler_till,
                            }),
                        )
                        if os.path.exists("latest_brawler_data.json"):
                            os.remove("latest_brawler_data.json")
                        print("Bot stopping: all targets completed.")
                        self.window_controller.keys_up(list("wasd"))
                        self.window_controller.close()
                        sys.exit(0)
            
            # Keep pressing the dismiss key on every iteration until the
            # end-of-match screens give way. One press is rarely enough in
            # showdown: after the place screen there can be star drops,
            # trophy rewards, and offers to dismiss.
            self.window_controller.press_key("Q")
            button_pressed = True

            time.sleep(self.end_screen_dismiss_delay)
            screenshot = self.window_controller.screenshot()
            current_state = get_state(screenshot)

        print("Game has ended", current_state)

    def quit_shop(self):
        self.window_controller.click(100*self.window_controller.width_ratio, 60*self.window_controller.height_ratio)

    def close_pop_up(self):
        screenshot = self.window_controller.screenshot()
        if self.close_popup_icon is None:
            self.close_popup_icon = load_image("images/states/close_popup.png", self.window_controller.scale_factor)
        popup_location = find_template_center(screenshot, self.close_popup_icon)
        if popup_location:
            self.window_controller.click(*popup_location)

    def do_state(self, state, data=None):
        if not str(state).startswith("end"):
            self.active_end_result = None
        if data is not None:
            self.states[state](data)
            return
        self.states[state]()
