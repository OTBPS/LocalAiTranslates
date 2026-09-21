function NormalizeVersion(Version: String): String;
var
  I, DotCount: Integer;
begin
  DotCount := 0;
  for I := 1 to Length(Version) do
    if Version[I] = '.' then
      DotCount := DotCount + 1;
  Result := Version;
  while DotCount < 3 do begin
    Result := Result + '.0';
    DotCount := DotCount + 1;
  end;
end;
function CompareSemanticVersions(LeftVersion, RightVersion: String): Integer;
var
  LeftPacked, RightPacked: Int64;
begin
  Result := 0;
  if StrToVersion(NormalizeVersion(LeftVersion), LeftPacked) and
     StrToVersion(NormalizeVersion(RightVersion), RightPacked) then
    Result := ComparePackedVersion(LeftPacked, RightPacked);
end;
