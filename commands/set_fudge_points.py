from core import *

@canvas_tool.command()
@click.argument('course_name')
@click.argument('quiz_name', default='')
@click.argument('points', default=-666, type=float)
@click.option('--dryrun/--no-dryrun', default=True, show_default=True,
              help="only show the grade, don't actually set it")
@click.option('--decrease/--no-decrease', default=False, show_default=True,
              help='If not true, the fudge points will not be updated if new points < old points.')
def set_fudge_points(course_name, quiz_name, points, dryrun, decrease):
    '''
    set the fudge points for a quiz.

    course_name - any part of an active course name. for example, 249 will match CS249.
    the course must active (it has not passed the end date) to be eligible for matching.
    only the first match will be used.

    quiz_name - any part of an quiz's name will be matched. if multiple quizes match, the
    points will not be set.
    '''

    canvas = get_canvas_object()

    course = get_course(canvas, course_name)

    quizzes = list(course.get_quizzes())
    selected_quizzes = [q for q in quizzes if quiz_name in q.title]

    if not selected_quizzes:
        error(f"could not find {quiz_name} in {', '.join([q.title for q in quizzes])}")
    elif len(selected_quizzes) > 1:
        error(f"multiple matches for {quiz_name}: {', '.join([q.title for q in selected_quizzes])}")
    else:
        for s in selected_quizzes[0].get_submissions():
            if points == -666:
                info(f"{s.user_id} {s.fudge_points}")
            else:
                if not decrease and s.fudge_points > points:
                    info(f"skipping {s.user_id} with {s.fudge_points} points")
                else:
                    if dryrun:
                        info(f"would update fudge points for {s.user_id} from {s.fudge_points} to {points}")
                    else:
                        info(f"updating fudge points for {s.user_id} from {s.fudge_points} to {points}")
                        # s.update_score_and_comments(fudge_points=points)
                        s.update_score_and_comments(quiz_submissions=[{"attempt": s.attempt, 'fudge_points': points}])