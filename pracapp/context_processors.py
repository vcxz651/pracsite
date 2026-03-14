from django.urls import reverse


def demo_context(request):
    scenario_label_map = {1: 'A', 2: 'B', 3: 'C'}
    scenario_date_map = {
        1: '지금은 4월 3일입니다. 밴드의 선곡회의가 막 끝난 시점입니다.',
        2: '지금은 4월 3일입니다. 오늘 우리 팀의 선곡회의가 있습니다.',
        3: '지금은 5월 18일입니다. 합주가 이미 시작된 시점입니다.',
    }
    session = request.session
    is_demo = bool(session.get('demo_mode'))
    resolver_match = getattr(request, 'resolver_match', None)
    demo_page_name = getattr(resolver_match, 'url_name', '') if resolver_match else ''
    demo_role = str(session.get('demo_role') or '').strip() if is_demo else ''
    demo_scenario = session.get('demo_scenario') if is_demo else None

    manager_id = str(session.get('demo_user_manager_id') or '').strip()
    member_id = str(session.get('demo_user_member_id') or '').strip()
    user_id = str(getattr(request.user, 'id', '') or '').strip() if getattr(request, 'user', None) and request.user.is_authenticated else ''

    is_demo_manager = bool(is_demo and user_id and user_id == manager_id)
    is_demo_member = bool(is_demo and user_id and user_id == member_id)
    demo_meeting_id = str(session.get('demo_meeting_id') or '').strip() if is_demo else ''
    demo_meeting_detail_url = ''
    if is_demo and demo_meeting_id:
        try:
            demo_meeting_detail_url = reverse('meeting_detail', kwargs={'pk': demo_meeting_id})
        except Exception:
            demo_meeting_detail_url = ''
    demo_tutorial_url = ''
    if is_demo:
        try:
            demo_tutorial_url = reverse('demo_feature_tutorial')
        except Exception:
            demo_tutorial_url = ''
    demo_scenario_url = ''
    if is_demo and demo_scenario in (1, 2, 3):
        try:
            demo_scenario_url = reverse('demo_scenario', kwargs={'scenario': int(demo_scenario)})
        except Exception:
            demo_scenario_url = ''
    demo_tutorial_mode = bool(is_demo and str(request.GET.get('tutorial') or '').strip() == '1')

    # 세션 role 값이 비어 있거나 유저와 불일치하면 현재 로그인 유저 기준으로 정규화
    if is_demo and user_id:
        if is_demo_manager and demo_role != 'manager':
            demo_role = 'manager'
            session['demo_role'] = demo_role
        elif is_demo_member and demo_role != 'member':
            demo_role = 'member'
            session['demo_role'] = demo_role

    return {
        'is_demo': is_demo,
        'show_demo_banner': bool(is_demo and demo_page_name != 'demo_home'),
        'demo_page_name': demo_page_name,
        'demo_role': demo_role,
        'demo_scenario': demo_scenario,
        'demo_scenario_label': scenario_label_map.get(demo_scenario),
        'demo_date_message': scenario_date_map.get(demo_scenario, ''),
        'demo_meeting_id': demo_meeting_id,
        'demo_meeting_detail_url': demo_meeting_detail_url,
        'demo_tutorial_url': demo_tutorial_url,
        'demo_scenario_url': demo_scenario_url,
        'demo_tutorial_mode': demo_tutorial_mode,
        'is_demo_manager': is_demo_manager,
        'is_demo_member': is_demo_member,
    }
