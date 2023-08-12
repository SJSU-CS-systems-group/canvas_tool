from core import *

@canvas_tool.command()
@click.option('--active/--inactive', default=True, help="show only active courses")
@click.option('--matcher', default=course_name_matcher, show_default=True, metavar="match_re_expression",
              help="course name regular expressions matcher")
@click.option('--formatter', default=course_name_formatter, show_default=True, metavar="format_re_expression", help="""
              course name regular expressions formatter based on the matcher pattern.
              a format pattern of - will turn off formatting.
              """)
def list_courses(active, matcher, formatter):
    '''list courses i am teaching. --inactive will include past and future courses.'''
    canvas = get_canvas_object()
    courses = get_courses(canvas, "", is_active=active)
    for c in courses:
        name = c.name if hasattr(c, "name") else "none"
        output(f"{c.id} {format_course_name(name, matcher, formatter)} {c.start:%Y-%m-%d} {c.end:%Y-%m-%d}")