from django.core.exceptions import ValidationError


class ModernKoreanPasswordValidator:
    """
    비밀번호 정책:
    - 6글자 이상
    """

    def validate(self, password, user=None):
        if password is None:
            raise ValidationError('비밀번호를 입력해 주세요.')

        if len(password) < 6:
            raise ValidationError("6글자 이상'만' 넘기세요. 대문자도, 특수문자도 필요 없습니다.")

    def get_help_text(self):
        return "6글자 이상'만' 넘기세요. 대문자도, 특수문자도 필요 없습니다."
