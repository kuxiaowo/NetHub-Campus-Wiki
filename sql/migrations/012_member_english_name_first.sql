BEGIN IMMEDIATE;

UPDATE people
SET display_name = CASE display_name
  WHEN '刘宙 Yoyo' THEN 'Yoyo 刘宙'
  WHEN '范森雅 Selina' THEN 'Selina 范森雅'
  WHEN '杨喜然 Roy' THEN 'Roy 杨喜然'
  WHEN '汪伯济 Eason' THEN 'Eason 汪伯济'
  WHEN '王美心 Marcia' THEN 'Marcia 王美心'
  WHEN '张雅婷 Abby' THEN 'Abby 张雅婷'
  WHEN '唐家悦 Aurora' THEN 'Aurora 唐家悦'
  WHEN '庞正心 Steve' THEN 'Steve 庞正心'
  WHEN '田思源 Kipper' THEN 'Kipper 田思源'
  WHEN '李郡雄 Leo' THEN 'Leo 李郡雄'
  WHEN '刘欣洲 Daniel' THEN 'Daniel 刘欣洲'
  WHEN '李亦涵 Nimo' THEN 'Nimo 李亦涵'
  WHEN '李柏鸿 Brandon' THEN 'Brandon 李柏鸿'
  WHEN '奥斯卡 Oscar' THEN 'Oscar 奥斯卡'
  WHEN '徐思成 Luke' THEN 'Luke 徐思成'
  WHEN '芦峻熙 Lucie' THEN 'Lucie 芦峻熙'
  ELSE display_name
END
WHERE display_name IN (
  '刘宙 Yoyo', '范森雅 Selina', '杨喜然 Roy', '汪伯济 Eason',
  '王美心 Marcia', '张雅婷 Abby', '唐家悦 Aurora', '庞正心 Steve',
  '田思源 Kipper', '李郡雄 Leo', '刘欣洲 Daniel', '李亦涵 Nimo',
  '李柏鸿 Brandon', '奥斯卡 Oscar', '徐思成 Luke', '芦峻熙 Lucie'
);

UPDATE project_members
SET display_name_snapshot = CASE display_name_snapshot
  WHEN '刘宙 Yoyo' THEN 'Yoyo 刘宙'
  WHEN '范森雅 Selina' THEN 'Selina 范森雅'
  WHEN '杨喜然 Roy' THEN 'Roy 杨喜然'
  WHEN '汪伯济 Eason' THEN 'Eason 汪伯济'
  WHEN '王美心 Marcia' THEN 'Marcia 王美心'
  WHEN '张雅婷 Abby' THEN 'Abby 张雅婷'
  WHEN '唐家悦 Aurora' THEN 'Aurora 唐家悦'
  WHEN '庞正心 Steve' THEN 'Steve 庞正心'
  WHEN '田思源 Kipper' THEN 'Kipper 田思源'
  WHEN '李郡雄 Leo' THEN 'Leo 李郡雄'
  WHEN '刘欣洲 Daniel' THEN 'Daniel 刘欣洲'
  WHEN '李亦涵 Nimo' THEN 'Nimo 李亦涵'
  WHEN '李柏鸿 Brandon' THEN 'Brandon 李柏鸿'
  WHEN '奥斯卡 Oscar' THEN 'Oscar 奥斯卡'
  WHEN '徐思成 Luke' THEN 'Luke 徐思成'
  WHEN '芦峻熙 Lucie' THEN 'Lucie 芦峻熙'
  ELSE display_name_snapshot
END
WHERE display_name_snapshot IN (
  '刘宙 Yoyo', '范森雅 Selina', '杨喜然 Roy', '汪伯济 Eason',
  '王美心 Marcia', '张雅婷 Abby', '唐家悦 Aurora', '庞正心 Steve',
  '田思源 Kipper', '李郡雄 Leo', '刘欣洲 Daniel', '李亦涵 Nimo',
  '李柏鸿 Brandon', '奥斯卡 Oscar', '徐思成 Luke', '芦峻熙 Lucie'
);

UPDATE projects
SET leader = CASE leader
  WHEN '刘宙 Yoyo' THEN 'Yoyo 刘宙'
  WHEN '庞正心 Steve' THEN 'Steve 庞正心'
  ELSE leader
END,
members = replace(
  replace(
    replace(
      replace(
        replace(
          replace(
            replace(
              replace(
                replace(
                  replace(
                    replace(
                      replace(
                        replace(
                          replace(
                            replace(
                              replace(members,
                                '刘宙 Yoyo', 'Yoyo 刘宙'),
                              '范森雅 Selina', 'Selina 范森雅'),
                            '杨喜然 Roy', 'Roy 杨喜然'),
                          '汪伯济 Eason', 'Eason 汪伯济'),
                        '王美心 Marcia', 'Marcia 王美心'),
                      '张雅婷 Abby', 'Abby 张雅婷'),
                    '唐家悦 Aurora', 'Aurora 唐家悦'),
                  '庞正心 Steve', 'Steve 庞正心'),
                '田思源 Kipper', 'Kipper 田思源'),
              '李郡雄 Leo', 'Leo 李郡雄'),
            '刘欣洲 Daniel', 'Daniel 刘欣洲'),
          '李亦涵 Nimo', 'Nimo 李亦涵'),
        '李柏鸿 Brandon', 'Brandon 李柏鸿'),
      '奥斯卡 Oscar', 'Oscar 奥斯卡'),
    '徐思成 Luke', 'Luke 徐思成'),
  '芦峻熙 Lucie', 'Lucie 芦峻熙');

PRAGMA user_version = 12;
COMMIT;
