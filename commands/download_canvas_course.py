from commands.upload_canvas_course import page_name_to_url
from core import *
from md2fhtml import *


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
        if hasattr(module, "completed_at") and module.completed_at:
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
    os.makedirs(target, exist_ok=True)
    for discussion in course.get_discussion_topics():
        # windows can't have : in the filename :'(
        target_file = os.path.join(target, discussion.title.strip().replace("\\", "-").replace(":", ";") + ".md")
        if os.path.exists(target_file):
            info(f"{target_file} already exists for {discussion.title}")
        else:
            if dryrun:
                info(f"would download {target_file} for {discussion.title}")
            else:
                info(f"downloading {target_file} for {discussion.title}")
                with open(target_file, "w+") as fd:
                    fd.write(f"# {discussion.title}\n")
                    # todo: we need to fix up the links based on the rr maps
                    fd.write(html2mdstr(discussion.message))


def download_assignments(course, target, dryrun):
    pass


def fix_links(text):
    # that funky ( [^\)]*) shouldn't be needed, but i do see trailing names after the URL
    return re.sub(r"\(https://\w+.instructure.com/courses/\w+/pages/([^ )]+)( [^\)]*)\)", r"(\1)", text)


def download_pages(course, target, dryrun):
    os.makedirs(target, exist_ok=True)
    for page in course.get_pages(include=["body"]):
        url = page_name_to_url(page.title)
        if page.url != url:
            warn(f"calculated page url for {page.title} ({url}) does not equal {page.url}")
        if dryrun:
            info(f"would download {page.title} to {url}")
        else:
            with open(os.path.join(target, url) + ".md", "w+") as fd:
                fd.write(f"published: {page.published}\n")
                if page.publish_at:
                    fd.write(f"publish_at: {page.publish_at}\n")
                if page.front_page:
                    fd.write(f"front_page: {page.front_page}\n")
                fd.write(f"title: {page.title}\n")
                fd.write(fix_links(html2mdstr(page.body)))


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
@click.option('--discussions/--no-discussions', default=False, show_default=True,
              help=f"download discussions to the {click.style('discussions', underline=True, italic=True)} subdirectory.")
@click.option('--assignments', default=False, show_default=True,
              help=f"download assignments to the {click.style('assignments', underline=True, italic=True)} subdirectory.")
@click.option('--pages/--no-pages', default=False, show_default=True,
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
