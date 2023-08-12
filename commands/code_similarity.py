from core import *

@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.argument('assignment_name', metavar='assignment', default='')
@click.argument('language', metavar='language')
@click.option('--dryrun/--no-dryrun', default=True, show_default=True,
              help="only show the grade, don't actually set it")
def code_similarity(course_name, language, assignment_name, dryrun):
    '''
    check submissions for code similarity using stanford MOSS.
    '''
    canvas = get_canvas_object()
    course = get_course(canvas, course_name)
    usermap = {u.id: u.name for u in course.get_users()}
    assignment = get_assignment(course, assignment_name)
    parser = ConfigParser()
    parser.read([config_ini])
    moss_userid = parser['MOSS']['userid']
    moss = mosspy.Moss(moss_userid, language)
    with tempfile.TemporaryDirectory("canvas_tool.attach") as tempdir:
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
        moss.addFilesByWildcard(f"{tempdir}/**/*.{language}")
        count = len(moss.files)
        with click.progressbar(length=count, label="uploading", item_show_func=lambda x: x) as bar:
            moss_url = moss.send(on_send=lambda fp, dn: bar.update(1, dn))
        print(moss_url)