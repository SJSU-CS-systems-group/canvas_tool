from core import *

@canvas_tool.command()
@click.argument("course")
@click.option('-t', 'thresholds', metavar='threshold', multiple=True, default=[84, 90, 95], show_default=True,
              type=click.INT, help="""
              assignment groups with grades about the lowest threshold will have a +, the next
              lowest gets ++, and so on. assignment groups below the lowest threshold will not
              be printed.
              """)
@click.option('-s', 'skip', metavar='skip_assignment', multiple=True, default=['iclickr', 'ungraded', 'imported'],
              show_default=True, help="""
              assignment groups with the listed keywords will not be collected.
              """)
def collect_reference_info(course, thresholds, skip):
    '''collect high level information about students of previous classes to help writing reference letters'''
    Grade = namedtuple('Grade', ['category', 'grade'])
    canvas = get_canvas_object()
    for course in get_courses(canvas, course, is_active=False, is_finished=True):
        results = canvas.graphql('query { course(id: "' + str(course.id) + '''") {
              assignmentGroupsConnection {
                  nodes { name
                          gradesConnection {
                              edges { node { currentScore
                                             enrollment { user { name } }
                                           } } } } } } }''')
        grades_by_student = defaultdict(list)

        for assignment_group in results['data']['course']['assignmentGroupsConnection']['nodes']:
            category = assignment_group['name']
            if any(x in category.lower() for x in skip):
                continue
            for grade in assignment_group['gradesConnection']['edges']:
                score = grade['node']['currentScore']
                name = grade['node']['enrollment']['user']['name']
                if score:
                    pluses = to_plus(score, thresholds)
                    if pluses:
                        grades_by_student[name].append(Grade(category, pluses))
        for i in grades_by_student.items():
            label = f'{i[0]}@{format_course_name(course.name)}'
            output(f'{label} {" ".join([g.category + ":" + g.grade for g in i[1]])}')

def to_plus(grade, levels):
    """ convert a score to a list of pluses based on grade """
    pluses = ""
    for level in levels:
        if grade >= level:
            pluses += '+'
    return pluses


