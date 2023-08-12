from core import *

@canvas_tool.command()
@click.argument('course')
@click.argument('subject')
@click.option('--course-in-subject/--no-course-in-subject', show_default=True, default=True,
              help='include the course name in []s in the subject line')
@click.option('--message', help="message to send")
@click.option('--from-file', help="file containing message to send (- for stdin)", type=click.File('r'))
@click.argument('students', nargs=-1, required=True)
def message_students(course, subject, message, course_in_subject, from_file, students):
    '''message students in a course'''
    canvas = get_canvas_object()
    course = get_course(canvas, course)

    message_to_send = ""
    if message:
        if not message.endswith("\n"):
            message += "\n"
        message_to_send += message
    if from_file:
        message_to_send += from_file.read()
    if not message and not from_file:
        error("either --message or --from_file must be specified")
        sys.exit(2)

    if course_in_subject:
        subject = f'[{format_course_name(course.name)}] {subject}'

    found_error = False
    to_message = []
    for student in students:
        users = list(course.get_users(search_term=student))
        if not len(users):
            error(f"could not find {student}")
            found_error = True
            continue
        elif len(users) > 1:
            error(f"multiple matches for {student}: {', '.join([str(u) for u in users])}")
            found_error = True
            continue
        to_message.append(users[0])
    if found_error:
        sys.exit(2)

    for user in to_message:
        # we set group_conversation to true to make sure it shows up as a new conversation
        canvas.create_conversation([user.id], message_to_send, subject=subject, group_conversation=True)