from core import *

@canvas_tool.command()
@click.argument("course")
@click.option("--round", default=0.0, help="points to add to the final score before calculating the letter grade.")
@click.option("--dryrun/--no-dryrun", default=True)
@click.option("--skip-mismatch/--no-skip-mismatch", default=True, help="do not set letter grade for current grades that don't match total")
def set_letter_grade(course, round, dryrun, skip_mismatch):
    ''' calculate the letter grade based on the final score in the class.

    the "Reported Letter Grade" assignment must be created in the gradebook as a letter grade assignment
    before this command is run.
    the command will loop through all the students in the class and set the letter grade in that assignment
    based on the final score in the class.
    '''

    canvas = get_canvas_object()
    course = get_course(canvas, course)

    rlg_assignment = get_assignment(course, "Reported Letter Grade")
    if not rlg_assignment:
        error('the "Reported Letter Grade" assignment hasn\'t been set up')
        exit(2)

    user_to_grade = {}
    for enrollment in course.get_enrollments(include=['grades']):
        if hasattr(enrollment, "grades"):
            current_score = enrollment.grades['current_score']
            final_score = enrollment.grades['final_score']
            if current_score != final_score:
                mess = f"current_score of {current_score} != {final_score} for {enrollment.user['name']} "
                if skip_mismatch:
                    warn(mess + "SKIPPED")
                    continue
                else:
                    warn(mess + "NOT SKIPPED")
            letter = points_to_letter(enrollment.grades['final_score'], round)
            user_to_grade[enrollment.user['id']] = (enrollment.user, letter, enrollment.grades['final_score'])

    if dryrun:
        for submission in rlg_assignment.get_submissions():
            if submission.user_id in user_to_grade:
                (user, letter, score) = user_to_grade[submission.user_id]
                info(f"{letter} {score} {user['name']}")
        warn("This was a dryrun. Nothing has been updated")
    else:
        with click.progressbar(length=len(user_to_grade), label="updating grades", show_pos=True) as bar:
            for submission in rlg_assignment.get_submissions():
                if submission.user_id in user_to_grade:
                    (user, letter, score) = user_to_grade[submission.user_id]
                    submission.edit(submission={'posted_grade': letter})
                    bar.update(1)
