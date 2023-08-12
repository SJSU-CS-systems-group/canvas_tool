from core import *


def download_modules(course, target, dryrun):
    def base_inner_module_to_str(module_item):
        return f'{"  " * (module_item.indent + 1)}* {sanitize(module_item.title)}; {module_item.type}{"" if module_item.published else "; published=False"}'

    def named_inner_module_to_str(module_item):
        module_item_target_name = None
        if hasattr(module_item, 'content_id'):
            module_item_target_name = rr4id[module_item.type + str(module_item.content_id)].name
        else:
            module_item_target_name = rr4url[module_item.page_url].name

        if module_item_target_name == module_item.title:
            module_item_target_name = None

        return f'{base_inner_module_to_str(module_item)}{f"; target={module_item_target_name}" if module_item_target_name else ""}'

    def external_tool(mi):
        return f'{base_inner_module_to_str(mi)}; newtab={"True" if mi.new_tab else "False"}; url={mi.external_url}'

    module_renderers = {
        "Assignment": named_inner_module_to_str,
        "File": named_inner_module_to_str,
        "Page": named_inner_module_to_str,
        "Quiz": named_inner_module_to_str,
        "Discussion": named_inner_module_to_str,
        "SubHeader": base_inner_module_to_str,
        "ExternalUrl": external_tool,
        "ExternalTool": external_tool,
    }

    top_modules = []
    id2name = {}
    output = ''
    for module in course.get_modules():
        id2name[module.id] = module.name
        ms = f"# {module.name}"
        if module.unlock_at:
            ms += f"; unlock={module.unlock_at}"
        if module.require_sequential_progress:
            ms += f"; sequential"
        if module.prerequisite_module_ids:
            ms += f"; prereqs={','.join([id2name[id] for id in module.prerequisite_module_ids])}"
        if module.completed_at:
            ms += f"; completed={module.completed_at}"
        if not module.published:
            ms += f"; published=False"
        output += ms + '\n'
        for item in module.get_module_items():
            if item.type in module_renderers:
                output += module_renderers[item.type](item) + '\n'
            else:
                warn(f"cannot render {item.__dict__}")

    if dryrun:
        info(f"would have written:\n{output}to {target}")
    else:
        with open(target, "w") as fd:
            fd.write(output)


def download_discussions(course, target, dryrun):
    pass


def download_assignments(course, target, dryrun):
    pass


def download_pages(course, target, dryrun):
    pass


def download_files(course, target, dryrun):
    class ToDownload(NamedTuple):
        file: canvasapi.file.File
        target: str

    error_seen = False
    to_download = []
    for folder in course.get_folders():
        target_dir = os.path.join(target, str(folder))
        if os.path.exists(target_dir):
            if not os.path.isdir(target_dir):
                error(f"{target_dir} is not a directory. skipping")
                error_seen = True
                continue
        else:
            if dryrun:
                info(f"would create {target_dir}")
            else:
                os.makedirs(target_dir)

        for file in folder.get_files():
            full_name = os.path.join(str(folder), str(file))
            target_file = os.path.join(target_dir, str(file))
            if dryrun:
                info(f"would download {full_name} to {target_file}")
            else:
                if os.path.exists(target_file):
                    warn(f"{target_file} already exists. skipping")
                else:
                    to_download.append(ToDownload(file, target_file))

    if to_download:
        with click.progressbar(to_download, label="downloading",
                               item_show_func=lambda i: str(i.file) if i else "") as tds:
            for td in tds:
                td.file.download(td.target)
    if error_seen:
        exit(2)


def download_announcements(course, target, dryrun):
    pass


@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.option('--dryrun/--no-dryrun', default=True, show_default=True, help="show what would happen, but don't do it.")
@click.option('--modules/--no-modules', default=False, show_default=True,
              help=f"download modules to the {click.style('modules', underline=True, italic=True)} file.")
@click.option('--discussions', default=False, show_default=True,
              help=f"download discussions to the {click.style('discussions', underline=True, italic=True)} subdirectory.")
@click.option('--assignments', default=False, show_default=True,
              help=f"download assignments to the {click.style('assignments', underline=True, italic=True)} subdirectory.")
@click.option('--pages', default=False, show_default=True,
              help=f"download pages to the {click.style('pages', underline=True, italic=True)} subdirectory.")
@click.option('--files', default=False, show_default=True,
              help=f"download files to the {click.style('files', underline=True, italic=True)} subdirectory.")
@click.option('--announcements', default=False, show_default=True,
              help=f"download announcements to the {click.style('announcements', underline=True, italic=True)} subdirectory.")
@click.option('--all/--no-all', default=False, show_default=True,
              help="download all content to corresponding directories")
@click.option("--target", default='.', show_default=True, help="download content parent directory.")
def download_course_content(course_name, dryrun, modules, discussions, assignments, pages, files, announcements, all,
                            target):
    """download course content from local files"""
    canvas = get_canvas_object()
    course = get_course(canvas, course_name, is_active=False)
    output(f"found {course.name}")
    map_course_resource_records(course)

    if all:
        modules = discussions = assignments = pages = files = announcements = True

    if not (modules or discussions or assignments or pages or files or announcements):
        error("nothing selected to download")
        exit(1)

    if modules:
        download_modules(course, os.path.join(target, 'modules'), dryrun)
    if discussions:
        download_discussions(course, os.path.join(target, 'discussions'), dryrun)
    if assignments:
        download_assignments(course, os.path.join(target, 'assignments'), dryrun)
    if pages:
        download_pages(course, os.path.join(target, 'pages'), dryrun)
    if files:
        download_files(course, os.path.join(target, 'files'), dryrun)
    if announcements:
        download_announcements(course, os.path.join(target, 'announcements'), dryrun)


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

def create_file(course, name, content=b''):
    last_slash = name.rindex("/")
    file = name[last_slash+1:]
    parent = name[0:last_slash] if last_slash != -1 else ""
    rc = course.upload(content, parent_folder_path=parent, name=file)
    process_resource_record(ResourceRecord(rc[1].id, base_url(rc[1].url), "File", name, not content))
    return rc[1]

def create_quiz(course, name, description=''):
    rc = course.create_quiz({"title": name, "description": description})
    process_resource_record(ResourceRecord(rc.id, base_url(rc.html_url), "Quiz", name, not description))
    return rc

def create_stub(course, item_type, item_name):
    if item_type =="Assignment":
        return create_assignment(course, item_name)
    if item_type == "Discussion":
        return create_discussion(course, item_name)
    if item_type == "File":
        return create_file(course, item_name)
    if item_type == "Quiz":
        return create_quiz(course, item_name)


def create_page(course, title, body = None):
    page_dict = {"title": title}
    if body:
        page_dict["body"] = body
    rc = course.create_page(page_dict)
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
                    last_module_item_names = set([mi.title for mi in course_modules[title].get_module_items()])
                    info(f"{title} module already present")
                elif dryrun:
                    info(f"would create {title} module")
                else:
                    info(f"creating {title} module")
                    last_module_seen = course.create_module({"name": title, "published": boolean_option("published", extract_options(parts[1])) if len(parts) > 1 else True})
                    course_modules[title] = last_module_seen
                    last_module_item_names = set()
            elif m:
                indent_level = len(m.group(1)) / 2
                item_title = m.group(3)
                item_parts = m.group(5).split(';', 1)
                item_options = extract_options(item_parts[1]) if len(item_parts) > 1 else {}
                item_type = item_parts[0].strip()
                if item_title in last_module_item_names:
                    info(f"item {item_title} present in {title}")
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
                        name_key = item_type+item_name
                        item_dict["content_id"] = rr4name[name_key].id if name_key in rr4name else create_stub(course, item_type, item_name).id
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
                        last_module_item_names.add(item_title)


def page_name_to_url(item_name):
    return item_name.lower().replace(" ", "-")


def extract_options(options):
    return {s[0].strip().lower(): s[1].strip() if len(s) > 1 else "" for s in [o.split('=', 2) for o in options.split(';')]}


def upload_discussions(course, target, dryrun):
    pass


def upload_assignments(course, target, dryrun):
    pass


def upload_pages(course, target, dryrun):
    pass


def upload_files(course, target, dryrun):
    # got to watch out for windows \\ when using join!
    to_upload = set([os.path.join(d, f)[len(target) + 1:].replace("\\", "/") for (d, sds, fs) in os.walk(target) for f in fs])

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
@click.option('--discussions', default=False, show_default=True,
              help=f"upload discussions to the {click.style('discussions', underline=True, italic=True)} subdirectory.")
@click.option('--assignments', default=False, show_default=True,
              help=f"upload assignments to the {click.style('assignments', underline=True, italic=True)} subdirectory.")
@click.option('--pages', default=False, show_default=True,
              help=f"upload pages to the {click.style('pages', underline=True, italic=True)} subdirectory.")
@click.option('--files', default=False, show_default=True,
              help=f"upload files to the {click.style('files', underline=True, italic=True)} subdirectory.")
@click.option('--announcements', default=False, show_default=True,
              help=f"upload announcements to the {click.style('announcements', underline=True, italic=True)} subdirectory.")
@click.option('--all/--no-all', default=False, show_default=True,
              help="upload all content to corresponding directories")
@click.option("--source", default='.', show_default=True, help="upload content parent directory.")
def upload_course_content(course_name, dryrun, modules, discussions, assignments, pages, files, announcements, all,
                          source):
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

    if modules:
        upload_modules(course, os.path.join(source, 'modules'), dryrun)
    if discussions:
        upload_discussions(course, os.path.join(source, 'discussions'), dryrun)
    if assignments:
        upload_assignments(course, os.path.join(source, 'assignments'), dryrun)
    if pages:
        upload_pages(course, os.path.join(source, 'pages'), dryrun)
    if files:
        upload_files(course, os.path.join(source, 'files'), dryrun)
    if announcements:
        upload_announcements(course, os.path.join(source, 'announcements'), dryrun)
