from core import *

@canvas_tool.command()
@click.argument('course')
@click.option('--active/--inactive', default=True, help="show only active courses")
@click.option('--emails/--no_emails', help="list student emails")
def list_students(course, active, emails):
    '''list the students in a course'''
    canvas = get_canvas_object()
    course = get_course(canvas, course, active)
    output(f"found {course.name}")
    info_keys = "name" + (" email" if emails else "")
    results = canvas.graphql('query { course(id: "' + str(course.id) + '''") {
               enrollmentsConnection { nodes { user {''' + info_keys + '''} } }
           } }''')
    for r in results['data']['course']['enrollmentsConnection']['nodes']:
        user = r['user']
        if emails:
            output(f"    {user['email']} {user['name']} ")
        else:
            output(f"    {user['name']} ")