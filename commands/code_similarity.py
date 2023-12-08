from core import *
import glob

@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.argument('assignment_name', metavar='assignment', default='')
@click.argument('language', metavar='language')
@click.option('--dryrun/--no-dryrun', default=True, show_default=True, help="only show the grade, don't actually set it")
@click.option('--pause/--no-pause', default=False, show_default=True, help="pause before uploading")
@click.option('--multiple/--no-multiple', default=False, show_default=True, help="collect submissions from multiple classes")
def code_similarity(course_name, language, assignment_name, dryrun, pause, multiple):
    '''
    check submissions for code similarity using stanford MOSS.
    '''
    canvas = get_canvas_object()
    courses = get_courses(canvas, course_name)
    if len(courses) == 0:
        error(f"no courses matched {course_name}")
        exit(2)
    if len(courses) > 1 and not multiple:
        error(f"multiple matches for {course_name}")
        for course in courses:
            error(f"    {course.name}")
        exit(2)

    parser = ConfigParser()
    parser.read([config_ini])
    moss_userid = parser['MOSS']['userid']

    moss = mosspy.Moss(moss_userid, language)
    with tempfile.TemporaryDirectory("canvas_tool.attach") as tempdir:
        for course in courses:
            assignment = get_assignment(course, assignment_name)
            usermap = {u.id: u.name for u in course.get_users()}
            submissions = list(assignment.get_submissions())
            with click.progressbar(length=len(submissions), label="downloading", item_show_func=lambda x: x) as bar:
                for sub in assignment.get_submissions():
                    if sub.user_id not in usermap:
                        continue
                    udir = f"{tempdir}/{usermap[sub.user_id]}"
                    os.makedirs(udir)
                    bar.update(1, usermap[sub.user_id])
                    for attachment in sub.attachments:
                        aname = f"{udir}/{attachment.filename}"
                        with open(aname, "wb") as f:
                            f.write(requests.get(attachment.url).content)
                        if aname.endswith(".zip"):
                            with zipfile.ZipFile(aname, "r") as zf:
                                zf.extractall(udir)
        files_to_upload = [x for x in glob.glob(f"{tempdir}/**/*.{language}") if '/__MACOSX/' not in x]
        info(f"uploading {files_to_upload}")

        if pause:
            input(f"pausing. code is in {tempdir}. hit enter to continue")
        if dryrun:
            info(f"would upload {len(files_to_upload)} files to MOSS")
        else:
            for file in files_to_upload:
                moss.addFile(file)
            count = len(moss.files)
            with click.progressbar(length=count, label="uploading", item_show_func=lambda x: x) as bar:
                moss_url = moss.send(on_send=lambda fp, dn: bar.update(1, dn))
            info(f"results at {moss_url}")
            info(f"download with: wget -k -e robots=off -np -r {moss_url}")
