from core import *

@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.argument('assignment_name', metavar='assignment', default='')
@click.option('--dryrun/--no-dryrun', default=True, show_default=True,
              help="only show the grade, don't actually set it")
def download_submissions(course_name, assignment_name, dryrun):
    '''
    download submissions for an assignment.
    '''

    canvas = get_canvas_object()

    course = get_course(canvas, course_name)

    assignment = get_assignment(course, assignment_name)

    query = """
    query submissions($assignmentid: ID!) {
        assignment(id: $assignmentid) { submissionsConnection {
            nodes { attachments { url displayName } user { name }
                    commentsConnection { nodes { comment attachments { url displayName}}}
            }
        }}
    }
    """
    result = canvas.graphql(query, {"assignmentid": assignment.id})
    submissions = result['data']['assignment']['submissionsConnection']['nodes']

    if dryrun:
        info(f"{len(submissions)} submissions to download")
        sys.exit(0)

    with click.progressbar(length=len(submissions), label="downloading submission", show_pos=True) as bar:
        for s in submissions:
            count = 1
            name = s['user']['name']
            dir = os.path.join(assignment_name, name.replace(' ', '-'))
            os.makedirs(dir, exist_ok=True)
            for a in s['attachments']:
                download_attachment(f'{dir}/submission{count}', a)
                count += 1
            count = 1
            for c in s['commentsConnection']['nodes']:
                with open(os.path.join(dir, f"comment{count}.txt"), 'w') as fd:
                    fd.write(c['comment'])
                subcount = 1
                for ca in c['attachments']:
                    download_attachment(f'{dir}/comment{count}attachment{subcount}', ca)
                    subcount += 1
                count += 1
            bar.update(1)



def download_attachment(basename, a):
    fname = a['displayName']
    suffix = os.path.splitext(fname)[1]
    durl = a['url']
    info(f'downloading {a}')
    with requests.get(durl) as response:
        if response.status_code != 200:
            error(f'error {response.status_code} fetching {durl}')
            return
        with open(f"{basename}{suffix}", "wb") as fd:
            for chunk in response.iter_content():
                fd.write(chunk)
