from canvasapi.page import Page

from core import *
from md2fhtml import md2htmlstr


def boolean_option(key, params):
    return params[key].lower() == "true" if key in params else False


def create_assignment(course, name, description=""):
    rc = course.create_assignment({"name": name, "description": description})
    process_resource_record(ResourceRecord(rc.id, base_url(rc.html_url), "Assignment", name, not description))
    return rc


def create_discussion(course, name, message=""):
    rc = course.create_discussion_topic(title=name, message=message)
    process_resource_record(ResourceRecord(rc.id, base_url(rc.html_url), "Discussion", name, not message))
    return rc


def create_file(course, name, content=b' '):
    last_slash = name.rindex("/")
    file = name[last_slash + 1:]
    parent = name[0:last_slash] if last_slash != -1 else ""
    rc = course.upload(content, parent_folder_path=parent, name=file)
    process_resource_record(ResourceRecord(rc[1].id, base_url(rc[1].url), "File", name, not content))
    return rc[1]


def create_quiz(course, name, description=''):
    rc = course.create_quiz({"title": name, "description": description})
    process_resource_record(ResourceRecord(rc.id, base_url(rc.html_url), "Quiz", name, not description))
    return rc


def create_stub(course, item_type, item_name):
    if item_type == "Assignment":
        return create_assignment(course, item_name)
    if item_type == "Discussion":
        return create_discussion(course, item_name)
    if item_type == "File":
        return create_file(course, item_name)
    if item_type == "Quiz":
        return create_quiz(course, item_name)


def create_page(course, title, body=None):
    page_dict = {"title": title}
    if body:
        page_dict["body"] = body
    rc = course.create_page(page_dict)
    process_resource_record(ResourceRecord(rc.page_id, rc.url, "Page", title, not body))
    return rc


def upload_modules(course, source, dryrun):
    last_module_seen = None
    last_module_item_names = set()
    with open(source, "r") as fd:
        for line in fd.readlines():
            m = re.match(r"^((  )+) ?\*\s+([^;]+)(;(.*)$)?", line)
            if line.startswith("# "):
                parts = line[2:].strip().split(";", 2)
                title = parts[0]
                if title in course_modules:
                    last_module_seen = course_modules[title]
                    last_module_item_names = set(
                        [f"{mi.type}; {mi.title}" for mi in course_modules[title].get_module_items()])
                    info(f"{title} module already present")
                elif dryrun:
                    info(f"would create {title} module")
                else:
                    info(f"creating {title} module")
                    last_module_seen = course.create_module({"name": title, "published": boolean_option("published",
                                                                                                        extract_options(
                                                                                                            parts[
                                                                                                                1])) if len(
                        parts) > 1 else True})
                    course_modules[title] = last_module_seen
                    last_module_item_names = set()
            elif m:
                indent_level = len(m.group(1)) / 2
                item_title = m.group(3)
                item_parts = m.group(5).split(';', 1)
                item_options = extract_options(item_parts[1]) if len(item_parts) > 1 else {}
                item_type = item_parts[0].strip()
                item_key = f"{item_type}; {item_title}"
                if item_key in last_module_item_names:
                    info(f"item {item_key} present in {title}")
                elif dryrun:
                    info(f"would create item {item_title} in {title}")
                else:
                    info(f"creating {item_title} in {title}")
                    item_dict = {"title": item_title, "indent": indent_level - 1, "type": item_type}
                    if "newtab" in item_options:
                        item_dict["newtab"] = boolean_option("newtab", item_options)
                    item_name = item_options["target"] if "target" in item_options else item_title
                    if item_type in ["Assignment", "Discussion", "File", "Quiz"]:
                        item_name = item_options["target"] if "target" in item_options else item_title
                        name_key = item_type + item_name
                        item_dict["content_id"] = rr4name[name_key].id if name_key in rr4name else create_stub(course,
                                                                                                               item_type,
                                                                                                               item_name).id
                    elif item_type == "Page":
                        url = page_name_to_url(item_name)
                        create_page(course, item_name)
                        item_dict["page_url"] = url
                    elif item_type.startswith("External"):
                        item_dict["external_url"] = item_options["url"]
                    if item_type == "ExternalTool":
                        error("ExternalTool creation not currently supported")
                    else:
                        last_module_seen.create_module_item(item_dict)
                        last_module_item_names.add(item_key)


def page_name_to_url(item_name):
    return item_name.lower().replace(" ", "-").replace(":", "").replace("--", '-')


def extract_options(options):
    return {s[0].strip().lower(): s[1].strip() if len(s) > 1 else "" for s in
            [o.split('=', 2) for o in options.split(';')]}


DISCUSSION_KEYWORDS = set(["title", "published", "publish_at"])


def upload_discussions(course, source, dryrun, force):
    to_upload = set(
        [os.path.join(d, f)[len(source) + 1:].replace("\\", "/") for (d, sds, fs) in os.walk(source) for f in fs])
    for file in to_upload:
        with open(os.path.join(source, file), "r") as fd:
            page = fd.read()
        dict = {}
        while True:
            (line, _, page) = page.partition('\n')
            (key, _, value) = line.partition(':')
            if key not in PAGE_KEYWORDS:
                warn(f"found unknown keyword {key} in {file}. ignoring")
            else:
                dict[key] = value.strip()
            if key == 'title':
                break
        dict['message'] = md2htmlstr(page)
        dict['discussion_type'] = 'threaded'
        rrkey = "Discussion" + dict['title']
        exists = rrkey in rr4name
        if exists:
            info(f"discussion {dict['title']} already exists")
        do_upload = not exists if not force else True
        if do_upload:
            if exists:
                if dryrun:
                    info(f"would update {dict['title']} from {file}")
                else:
                    info(f"updating {dict['title']} from {file}")
                    dict['title'] = dict['title'] + "blah"
                    dt = course.get_discussion_topic(rr4name[rrkey].id)
                    rc = dt.update(**dict)
            else:
                if dryrun:
                    info(f"would create {dict['title']} from {file}")
                else:
                    info(f"creating {dict['title']} from {file}")
                    rc = course.create_discussion_topic(**dict)
                    process_resource_record(ResourceRecord(rc.id, base_url(rc.html_url), "Discussion", rc.title, False))


def upload_assignments(course, target, dryrun):
    pass


PAGE_KEYWORDS = set(["title", "published", "publish_at", "front_page"])


def upload_pages(course, source, dryrun, force):
    # got to watch out for windows \\ when using join!
    to_upload = set(
        [os.path.join(d, f)[len(source) + 1:].replace("\\", "/") for (d, sds, fs) in os.walk(source) for f in fs])
    for file in to_upload:
        with open(os.path.join(source, file), "r") as fd:
            page = fd.read()
        dict = {}
        while True:
            (line, _, page) = page.partition('\n')
            (key, _, value) = line.partition(':')
            if key not in PAGE_KEYWORDS:
                warn(f"found unknown keyword {key} in {file}. ignoring")
            else:
                dict[key] = value.strip()
            if key == 'title':
                break
        dict['body'] = md2htmlstr(page)
        rrkey = "Page" + dict['title']
        exists = rrkey in rr4name
        if exists:
            info(f"page {dict['title']} already exists")
        do_upload = not exists if not force else True
        if do_upload:
            if exists:
                if dryrun:
                    info(f"would update {dict['title']} from {file}")
                else:
                    info(f"updating {dict['title']} from {file}")
                    dict['title'] = dict['title'] + "blah"
                    p: Page = course.get_page(rr4name[rrkey].url)
                    rc = p.edit(**dict)
            else:
                if dryrun:
                    info(f"would create {dict['title']} from {file}")
                else:
                    info(f"creating {dict['title']} from {file}")
                    rc = course.create_page(dict)
                    process_resource_record(ResourceRecord(rc.page_id, rc.url, "Page", rc.title, False))


def upload_files(course, target, dryrun):
    # got to watch out for windows \\ when using join!
    to_upload = set(
        [os.path.join(d, f)[len(target) + 1:].replace("\\", "/") for (d, sds, fs) in os.walk(target) for f in fs])

    existing_files = set()
    for folder in course.get_folders():
        for file in folder.get_files():
            existing_files.add(os.path.join(str(folder), str(file)).replace("\\", "/"))
    for common in to_upload.intersection(existing_files):
        warn(f"{common} already exists. skipping.")

    uploads = list(to_upload.difference(existing_files))
    if dryrun:
        for up in uploads:
            name = os.path.basename(up)
            parent = os.path.dirname(up)
            info(f"would upload {name} to {parent}")
    else:
        with click.progressbar(uploads, label="uploading",
                               item_show_func=lambda i: i if i else "") as ups:
            for up in ups:
                name = os.path.basename(up)
                parent = os.path.dirname(up)
                filename = os.path.join(target, up)
                if os.stat(filename).st_size > 0:
                    course.upload(os.path.join(target, up), parent_folder_path=parent, name=name)


def upload_announcements(course, target, dryrun):
    pass


@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.option('--dryrun/--no-dryrun', default=True, show_default=True, help="show what would happen, but don't do it.")
@click.option('--modules/--no-modules', default=False, show_default=True,
              help=f"upload modules to the {click.style('modules', underline=True, italic=True)} subdirectory.")
@click.option('--discussions/--no-discussions', default=False, show_default=True,
              help=f"upload discussions to the {click.style('discussions', underline=True, italic=True)} subdirectory.")
@click.option('--assignments', default=False, show_default=True,
              help=f"upload assignments to the {click.style('assignments', underline=True, italic=True)} subdirectory.")
@click.option('--pages/--no-pages', default=False, show_default=True,
              help=f"upload pages to the {click.style('pages', underline=True, italic=True)} subdirectory.")
@click.option('--files/--no-files', default=False, show_default=True,
              help=f"upload files to the {click.style('files', underline=True, italic=True)} subdirectory.")
@click.option('--announcements', default=False, show_default=True,
              help=f"upload announcements to the {click.style('announcements', underline=True, italic=True)} subdirectory.")
@click.option('--all/--no-all', default=False, show_default=True,
              help="upload all content to corresponding directories")
@click.option("--source", default='.', show_default=True, help="upload content parent directory.")
@click.option("--force/--no-force", default=False, show_default=True, help="overwrite existing content")
def upload_course_content(course_name, dryrun, modules, discussions, assignments, pages, files, announcements, all,
                          source, force):
    """upload course content from local files"""
    canvas = get_canvas_object()
    course = get_course(canvas, course_name, is_active=False)
    output(f"found {course.name}")
    map_course_resource_records(course)

    if all:
        modules = discussions = assignments = pages = files = announcements = True

    if not (modules or discussions or assignments or pages or files or announcements):
        error("nothing selected to upload")
        exit(1)

    if discussions:
        upload_discussions(course, os.path.join(source, 'discussions'), dryrun, force)
    if assignments:
        upload_assignments(course, os.path.join(source, 'assignments'), dryrun)
    if pages:
        upload_pages(course, os.path.join(source, 'pages'), dryrun, force)
    if files:
        upload_files(course, os.path.join(source, 'files'), dryrun)
    if announcements:
        upload_announcements(course, os.path.join(source, 'announcements'), dryrun)
    if modules:
        upload_modules(course, os.path.join(source, 'modules'), dryrun)
