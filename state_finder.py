import os
import sys
import cv2
import numpy as np
sys.path.append(os.path.abspath('/'))
from utils import load_toml_as_dict

orig_screen_width, orig_screen_height = 1920, 1080

states_path = r"./images/states/"

star_drops_path = r"./images/star_drop_types/"
images_with_star_drop = []
for file in os.listdir(star_drops_path):
    if "star_drop" in file:
        images_with_star_drop.append(file)
images_with_star_drop.sort(key=lambda name: 0 if name in ("angelic_star_drop.png", "demonic_star_drop.png") else 1)

end_results_path = r"./images/end_results/"

region_data = load_toml_as_dict("./cfg/lobby_config.toml")['template_matching']
super_debug = load_toml_as_dict("./cfg/general_config.toml")['super_debug'] == "yes"
_last_printed_state = None
if super_debug:
    debug_folder = "./debug_frames/"
    if not os.path.exists(debug_folder):
        os.makedirs(debug_folder)

def is_template_in_region(image, template_path, region, threshold=0.7):
    current_height, current_width = image.shape[:2]
    orig_x, orig_y, orig_width, orig_height = region
    width_ratio, height_ratio = current_width / orig_screen_width, current_height / orig_screen_height

    new_x, new_y = int(orig_x * width_ratio), int(orig_y * height_ratio)
    new_width, new_height = int(orig_width * width_ratio), int(orig_height * height_ratio)
    cropped_image = image[new_y:new_y + new_height, new_x:new_x + new_width]
    current_height, current_width = image.shape[:2]
    loaded_template = load_template(template_path, current_width, current_height)
    result = cv2.matchTemplate(cropped_image, loaded_template,
                               cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    return max_val > threshold

cached_templates = {}

def load_template(image_path, width, height):
    if (image_path, width, height) in cached_templates:
        return cached_templates[(image_path, width, height)]
    current_width_ratio, current_height_ratio = width / orig_screen_width, height / orig_screen_height
    image = cv2.imread(image_path)
    orig_height, orig_width = image.shape[:2]
    resized_image = cv2.resize(image, (int(orig_width * current_width_ratio), int(orig_height * current_height_ratio)))
    cached_templates[(image_path, width, height)] = resized_image
    return resized_image

crop_region = load_toml_as_dict("./cfg/lobby_config.toml")['lobby']['trophy_observer']
_current_gamemode = load_toml_as_dict("./cfg/bot_config.toml").get("gamemode", "")

# Showdown has place-based results (1st-4th in trio) instead of victory/defeat.
# Each place may have multiple template variants (different backgrounds at
# different trophy ranges). Any matching variant counts as that place.
showdown_place_templates = {
    "1st": ["sd1st.png"],
    "2nd": ["sd2nd.png"],
    "4th": ["sd4th.png"],
    "3rd": ["sd3rd.png", "sd3rd_alt.png"],
}


SHOWDOWN_PLACE_THRESHOLD = 0.95


def refresh_runtime_config():
    global region_data, super_debug, crop_region, _current_gamemode
    lobby_config = load_toml_as_dict("./cfg/lobby_config.toml")
    general_config = load_toml_as_dict("./cfg/general_config.toml")
    bot_config = load_toml_as_dict("./cfg/bot_config.toml")
    region_data = lobby_config['template_matching']
    crop_region = lobby_config['lobby']['trophy_observer']
    super_debug = str(general_config.get("super_debug", "no")).lower() in ("yes", "true", "1")
    _current_gamemode = bot_config.get("gamemode", "")
    if super_debug and not os.path.exists("./debug_frames/"):
        os.makedirs("./debug_frames/")


def find_game_result(screenshot):
    if _current_gamemode == "showdown":
        for place, template_files in showdown_place_templates.items():
            for template_file in template_files:
                if is_template_in_region(
                    screenshot,
                    end_results_path + template_file,
                    crop_region,
                    threshold=SHOWDOWN_PLACE_THRESHOLD,
                ):
                    return place
        return False

    is_victory = is_template_in_region(screenshot, end_results_path + 'victory.png', crop_region)
    if is_victory:
        return "victory"

    is_defeat = is_template_in_region(screenshot, end_results_path + 'defeat.png', crop_region)
    if is_defeat:
        return "defeat"

    is_draw = is_template_in_region(screenshot, end_results_path + 'draw.png', crop_region)
    if is_draw:
        return "draw"
    return False



def get_in_game_state(image):
    game_result = is_in_end_of_a_match(image)
    if game_result: return f"end_{game_result}"
    if is_in_shop(image): return "shop"
    if is_in_offer_popup(image): return "popup"
    if is_in_lobby(image): return "lobby"
    if is_in_brawler_selection(image):
        return "brawler_selection"

    if is_in_brawl_pass(image) or is_in_star_road(image):
        return "shop"

    if is_in_star_drop(image):
        return "star_drop"

    if is_in_trophy_reward(image):
        return "trophy_reward"

    if is_in_prestige_reward(image):
        return "prestige_reward"

    return "match"


def is_in_shop(image) -> bool:
    return is_template_in_region(image, states_path + 'powerpoint.png', region_data["powerpoint"])


def is_in_brawler_selection(image) -> bool:
    return is_template_in_region(image, states_path + 'brawler_menu_task.png', region_data["brawler_menu_task"])


def is_in_offer_popup(image) -> bool:
    return is_template_in_region(image, states_path + 'close_popup.png', region_data["close_popup"])


def is_in_lobby(image) -> bool:
    return (
        is_template_in_region(image, states_path + 'lobby_menu.png', region_data["lobby_menu"])
        or is_lobby_play_button_visible(image)
    )


def is_lobby_play_button_visible(image) -> bool:
    current_height, current_width = image.shape[:2]
    width_ratio = current_width / orig_screen_width
    height_ratio = current_height / orig_screen_height

    # The lobby has a large yellow PLAY button in the lower-right. This keeps
    # lobby frames out of the expensive match loop when the small menu template
    # misses on some emulator resolutions or skins.
    region = [1260, 820, 610, 225]
    x = int(region[0] * width_ratio)
    y = int(region[1] * height_ratio)
    w = int(region[2] * width_ratio)
    h = int(region[3] * height_ratio)
    crop = image[y:y + h, x:x + w]
    if crop.size == 0:
        return False

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    yellow_mask = cv2.inRange(
        hsv,
        np.array((15, 90, 120), dtype=np.uint8),
        np.array((42, 255, 255), dtype=np.uint8),
    )
    yellow_pixels = cv2.countNonZero(yellow_mask)
    yellow_ratio = yellow_pixels / max(1, crop.shape[0] * crop.shape[1])
    if yellow_ratio < 0.28:
        return False

    contours, _ = cv2.findContours(yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False
    largest = max(contours, key=cv2.contourArea)
    bx, by, bw, bh = cv2.boundingRect(largest)
    return bw > w * 0.45 and bh > h * 0.35


def is_in_end_of_a_match(image):
    return find_game_result(image)



def is_in_trophy_reward(image):
    return is_template_in_region(image, states_path + 'trophies_screen.png', region_data["trophies_screen"])


def count_hsv_in_region(image, region, lower, upper):
    current_height, current_width = image.shape[:2]
    orig_x, orig_y, orig_width, orig_height = region
    width_ratio, height_ratio = current_width / orig_screen_width, current_height / orig_screen_height
    x = int(orig_x * width_ratio)
    y = int(orig_y * height_ratio)
    width = int(orig_width * width_ratio)
    height = int(orig_height * height_ratio)
    crop = image[y:y + height, x:x + width]
    if crop.size == 0:
        return 0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))
    return int(cv2.countNonZero(mask))


def is_in_prestige_reward(image):
    current_height, current_width = image.shape[:2]
    width_ratio = current_width / orig_screen_width
    height_ratio = current_height / orig_screen_height

    button_region = [1210, 895, 360, 135]
    x = int(button_region[0] * width_ratio)
    y = int(button_region[1] * height_ratio)
    w = int(button_region[2] * width_ratio)
    h = int(button_region[3] * height_ratio)
    button_crop = image[y:y + h, x:x + w]
    if button_crop.size == 0:
        return False

    hsv = cv2.cvtColor(button_crop, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(
        hsv,
        np.array((50, 150, 130), dtype=np.uint8),
        np.array((72, 255, 255), dtype=np.uint8),
    )
    contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False
    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    bx, by, bw, bh = cv2.boundingRect(largest)
    crop_area = max(1, button_crop.shape[0] * button_crop.shape[1])
    green_ratio = cv2.countNonZero(green_mask) / crop_area
    if area < crop_area * 0.35 or green_ratio < 0.30 or bw < w * 0.55 or bh < h * 0.35:
        return False

    text_region = [1320, 930, 180, 55]
    tx = int(text_region[0] * width_ratio)
    ty = int(text_region[1] * height_ratio)
    tw = int(text_region[2] * width_ratio)
    th = int(text_region[3] * height_ratio)
    text_crop = image[ty:ty + th, tx:tx + tw]
    if text_crop.size == 0:
        return False
    text_hsv = cv2.cvtColor(text_crop, cv2.COLOR_BGR2HSV)
    white_mask = cv2.inRange(
        text_hsv,
        np.array((0, 0, 180), dtype=np.uint8),
        np.array((179, 90, 255), dtype=np.uint8),
    )
    white_pixels = cv2.countNonZero(white_mask)
    if white_pixels < max(120, int(text_crop.shape[0] * text_crop.shape[1] * 0.08)):
        return False

    prestige_purple = count_hsv_in_region(
        image,
        [1080, 140, 620, 570],
        (124, 80, 90),
        (162, 255, 255),
    )
    return prestige_purple > 35000



def is_in_brawl_pass(image):
    return is_template_in_region(image, states_path + 'brawl_pass_house.PNG', region_data['brawl_pass_house'])


def is_in_star_road(image):
    return is_template_in_region(image, states_path + "go_back_arrow.png", region_data['go_back_arrow'])


def is_in_star_drop(image):
    return get_star_drop_type(image) is not None


def get_star_drop_type(image):
    for image_filename in images_with_star_drop:
        if is_template_in_region(image, star_drops_path + image_filename, region_data['star_drop']):
            if image_filename == "angelic_star_drop.png":
                return "angelic"
            if image_filename == "demonic_star_drop.png":
                return "demonic"
            return "standard"
    return None

def get_state(screenshot):
    global _last_printed_state
    refresh_runtime_config()
    screenshot_bgr = cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)
    if super_debug: cv2.imwrite(f"./debug_frames/state_screenshot_{len(os.listdir('./debug_frames'))}.png", screenshot_bgr)
    state = get_in_game_state(screenshot_bgr)
    if super_debug or state != _last_printed_state:
        print(f"State: {state}")
        _last_printed_state = state
    return state
