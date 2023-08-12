from core import *

@canvas_tool.command()
@click.argument("course")
@click.option('-m', 'min_grade', default=50.0, show_default=True, help="""
              the minimum assignment grade. any score below this grade will be set to
              this minimum score.
              """)
def min_grade_analyzer(course, min_grade):
    '''see what the scores would look like with minimum grade'''
    canvas = get_canvas_object()
    min_grade = min_grade / 100
    for course in get_courses(canvas, course, is_active=False, is_finished=True):
        # first get all the grade categories and track the ones with weights
        results = canvas.graphql('query { course(id: "' + str(course.id) + '''") {
                    enrollmentsConnection {
                        nodes {
                            grades { currentScore }
                            user { name }
                        }
                    }
                    assignmentGroupsConnection {
                      nodes {
                        groupWeight
                        name
                        id
                      }
                    }
                  }
                } ''')
        class_grade_by_student = {}
        for enrollment in results['data']['course']['enrollmentsConnection']['nodes']:
            class_grade_by_student[enrollment['user']['name']] = enrollment['grades']['currentScore']

        grades_by_student = defaultdict(lambda: defaultdict(list))
        assignment_groups = [assignment_group for assignment_group in
                             results['data']['course']['assignmentGroupsConnection']['nodes'] if
                             assignment_group['groupWeight']]
        weights = {}
        for assignment_group in assignment_groups:
            category = assignment_group['name']
            weight = assignment_group['groupWeight']
            weights[category] = weight
            assignment_group_id = assignment_group['id']
            assignments = canvas.graphql('query { assignmentGroup(id: "' + assignment_group_id + '''") {
                                         assignmentsConnection {
                                             nodes {
                                                 id
                                                 name
                                             }
                                         }}}''')
            for assignment in assignments['data']['assignmentGroup']['assignmentsConnection']['nodes']:
                assignment_id = assignment['id']
                scores = canvas.graphql('query { assignment(id: "' + assignment_id + '''") {
                                             name
                                             pointsPossible
                                             submissionsConnection {
                                                 nodes {
                                                     score
                                                      user { name }
                                                 }
                                             }
                                         } }''')
                points_possible = scores['data']['assignment']['pointsPossible']
                for score in scores['data']['assignment']['submissionsConnection']['nodes']:
                    currentScore = score['score']
                    name = score['user']['name']
                    if currentScore == None:
                        continue
                    grades_by_student[name][category].append((currentScore, points_possible))

        for (name, assignments) in grades_by_student.items():
            total = 0.0
            min_total = 0.0
            components = []
            for (cat, scores) in assignments.items():
                cat_total = sum([current_score for (current_score, points_possible) in scores])
                min_scores = [(
                    current_score if not points_possible or current_score >= points_possible * min_grade else points_possible * min_grade,
                    points_possible) for (current_score, points_possible) in scores]
                min_cat_total = sum([current_score for (current_score, points_possible) in min_scores])
                cat_possible = sum([points_possible for (current_score, points_possible) in scores])
                if cat_possible == 0:
                    cat_possible = 100
                cat_avg = cat_total / cat_possible
                min_avg = min_cat_total / cat_possible
                inc = cat_avg * weights[cat]
                min_inc = min_avg * weights[cat]
                total += inc
                min_total += min_inc
                components.append((cat,cat_avg * 100))
                # print(f'{scores} {cat_avg} {weights[cat]} {inc} {total} {min_total} {" " if total == min_total else "*****"}')
            letter = to_letter_grade(total)
            min_letter = to_letter_grade(min_total)
            if letter != min_letter:
                output(f'{name}@{class_grade_by_student[name]}@{total}({letter}) {min_total}({min_letter})')

