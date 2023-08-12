from core import *

@canvas_tool.command()
def help_me_setup():
    """provide guidance through the setup process"""
    if os.path.isfile(config_ini):
        info(f"great! {config_ini} exists. let's check it!")
    else:
        error(f"""{config_ini} does not exist. you need to create it.
it should have the form:""")
        print_config_ini_format(True)
        sys.exit(2)

    parser = ConfigParser()
    try:
        parser.read([config_ini])
    except:
        error(f"there was a problem reading {config_ini}. make sure it has the format of:")
        print_config_ini_format(False)

    check_key("SERVER", parser)
    url = check_key("url", parser["SERVER"])
    p = urllib.parse.urlparse(url)
    if p.scheme != "https":
        error(f"url in {config_ini} must start with https://")
        sys.exit(2)

    if p.path:
        error(f"url in {config_ini} must have the form http://hostname with no other /")
        sys.exit(2)

    try:
        with urllib.request.urlopen(url) as con:
            info(f"{url} is reachable.")
    except Exception as e:
        error(f"got '{e}' accessing {url}. please check the url in {config_ini}.")
        sys.exit(2)

    token = check_key("token", parser["SERVER"])
    if token and len(token) > 20:
        info(f"token found. checking to see if it is usable")
    else:
        error(f"token is too short. make sure you have copied it correctly from canvas.")
        sys.exit(2)

    try:
        canvas = Canvas(url, token)
        info(f"you are successfully able to use canvas as {canvas.get_current_user().name}")
    except Exception as e:
        error(f"problem accessing canvas: {e}")
        sys.exit(2)

    sys.exit(0)
